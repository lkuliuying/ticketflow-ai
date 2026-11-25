from datetime import timedelta
from io import BytesIO
from unittest.mock import patch
from uuid import uuid4

import pytest
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError
from django.utils import timezone
from PIL import Image

from file.models import UploadFile
from file.services.cleanup import auto_clean_upload_file
from file.utils.upload_store import get_upload_max_size
from identity.models import UserInfo
from system.models import Menu
from tests.integration.tickets.test_ticket_api import assert_error, authenticated
from tickets.cache import TICKET_CACHE_KEY_PREFIX, check_rate
from tickets.chat_services import send_chat_message
from tickets.models import Status, Ticket, TicketChatMessage
from tickets.policy import TicketAccess
from tickets.tasks import cleanup_expired_ticket_videos

pytestmark = pytest.mark.django_db
TICKETS = "/api/tickets"


def make_png(name: str = "error.png") -> SimpleUploadedFile:
    buf = BytesIO()
    Image.new("RGB", (16, 16), color=(20, 120, 220)).save(buf, format="PNG")
    return SimpleUploadedFile(name, buf.getvalue(), content_type="image/png")


def make_mp4(name: str = "repro.mp4") -> SimpleUploadedFile:
    payload = b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom" + b"\x00" * 64
    return SimpleUploadedFile(name, payload, content_type="video/mp4")


def test_create_ticket_with_images_and_authorized_access(users, client_for, details):
    requester = client_for(users["requester"])
    bad_svg = SimpleUploadedFile("xss.svg", b"<svg onload=alert(1)></svg>", content_type="image/svg+xml")
    assert_error(requester.post(f"{TICKETS}/attachments/upload", {"file": bad_svg}, format="multipart"), 400)
    assert_error(requester.post(f"{TICKETS}/attachments/upload", {"file": make_mp4()}, format="multipart"), 400)

    uploaded = requester.post(f"{TICKETS}/attachments/upload", {"file": make_png()}, format="multipart")
    assert uploaded.status_code == 201, uploaded.data
    file_pk = uploaded.data["data"]["file_pk"]

    key = str(uuid4())
    payload = {**details, "attachment_ids": [file_pk]}
    created = requester.post(TICKETS, payload, format="json", HTTP_IDEMPOTENCY_KEY=key)
    assert created.status_code == 201, created.data
    ticket_pk = created.data["data"]["pk"]

    detail = requester.get(f"{TICKETS}/{ticket_pk}")
    assert detail.status_code == 200, detail.data
    attachments = detail.data["data"]["attachments"]
    assert len(attachments) == 1
    assert attachments[0]["filename"] == "error.png"

    fetched = requester.get(attachments[0]["url"])
    assert fetched.status_code == 200
    assert fetched["Content-Type"] == "image/png"
    thumb = requester.get(attachments[0]["thumb_url"])
    assert thumb.status_code == 200

    outsider = UserInfo.objects.create_user(username="att-outsider")
    outsider.roles.set(users["requester"].roles.all())
    assert_error(client_for(outsider).get(attachments[0]["url"]), 404)


def test_ticket_chat_lifecycle_media_range_unread_and_video_cleanup(users, make_ticket, client_for):
    ticket = make_ticket(status=Status.OPEN, assignee=users["agent"])
    resource = f"{TICKETS}/{ticket.pk}"
    requester = client_for(users["requester"])
    agent = client_for(users["agent"])
    admin = client_for(users["admin"])

    # OPEN: chat is locked until technician accepts.
    state = requester.get(f"{resource}/chat/messages").data["data"]["chat_state"]
    assert state == {"can_send": False, "lock_reason": "WAITING_ACCEPT"}
    assert_error(requester.post(f"{resource}/chat/messages", {"kind": "TEXT", "content": "您好"}, format="json"), 403)

    # Technician accepts -> IN_PROGRESS unlocks chat.
    accepted = agent.post(
        f"{resource}/transition", {"target_status": Status.IN_PROGRESS, "version": ticket.version}, format="json"
    )
    assert accepted.status_code == 200
    assert requester.get(f"{resource}/chat/messages").data["data"]["chat_state"]["can_send"] is True

    # Idempotent TEXT send + first_response_at on technician reply.
    cid = str(uuid4())
    first = agent.post(
        f"{resource}/chat/messages",
        {"kind": "TEXT", "content": "请发下报错录屏", "client_msg_id": cid},
        format="json",
    )
    assert first.status_code == 201, first.data
    replay = agent.post(
        f"{resource}/chat/messages",
        {"kind": "TEXT", "content": "请发下报错录屏", "client_msg_id": cid},
        format="json",
    )
    assert replay.status_code == 200 and replay.data["data"]["id"] == first.data["data"]["id"]
    ticket.refresh_from_db()
    assert ticket.first_response_at is not None

    # Unread count on list for requester, cleared after chat/read.
    rows = requester.get(TICKETS).data["data"]["results"]
    assert rows[0]["unread_chat_count"] == 1
    assert requester.post(f"{resource}/chat/read").status_code == 200
    assert requester.get(TICKETS).data["data"]["results"][0]["unread_chat_count"] == 0

    # Video upload + message + HTTP Range 206 streaming.
    vid_up = requester.post(f"{resource}/chat/upload", {"file": make_mp4()}, format="multipart")
    assert vid_up.status_code == 201, vid_up.data
    vid_msg = requester.post(
        f"{resource}/chat/messages",
        {"kind": "VIDEO", "file_pk": vid_up.data["data"]["file_pk"], "content": "复现录屏"},
        format="json",
    )
    assert vid_msg.status_code == 201, vid_msg.data
    video_url = vid_msg.data["data"]["file_url"]
    partial = agent.get(video_url, HTTP_RANGE="bytes=0-15")
    assert partial.status_code == 206
    assert partial["Content-Range"].startswith("bytes 0-15/")
    assert len(b"".join(partial.streaming_content)) == 16

    # AI context includes recent chat messages.
    ai_ctx = agent.get(f"{resource}/ai-context").data["data"]
    assert len(ai_ctx["recent_messages"]) == 2
    assert any("报错录屏" in row["content"] for row in ai_ctx["recent_messages"])

    # Return ticket -> OPEN & unassigned, chat locked again.
    returned = agent.post(f"{resource}/return", {"version": ticket.version, "reason": "转网络组"}, format="json")
    assert returned.status_code == 200
    assert returned.data["data"]["status"] == Status.OPEN
    assert requester.get(f"{resource}/chat/messages").data["data"]["chat_state"]["can_send"] is False

    # Close ticket -> chat archived read-only, and video cleanup expires >90d videos.
    Ticket.objects.filter(pk=ticket.pk).update(status=Status.CLOSED, updated_time=timezone.now() - timedelta(days=91))
    assert admin.get(f"{resource}/chat/messages").data["data"]["chat_state"] == {
        "can_send": False,
        "lock_reason": "CLOSED",
    }
    assert cleanup_expired_ticket_videos.run(days=90) == 1
    assert TicketChatMessage.objects.get(pk=vid_msg.data["data"]["id"]).media_expired is True
    assert_error(admin.get(video_url), 404)


@pytest.mark.parametrize(
    "params",
    [
        {"before_id": "invalid"},
        {"after_id": "123"},
        {"limit": "oops"},
        {"limit": 0},
        {"limit": 101},
        {"before_id": str(uuid4()), "after_id": str(uuid4())},
        {"after_id": str(uuid4())},
    ],
)
def test_chat_rejects_invalid_pagination(users, make_ticket, client_for, params):
    ticket = make_ticket(assignee=users["agent"])
    assert_error(client_for(users["requester"]).get(f"{TICKETS}/{ticket.pk}/chat/messages", params), 400)


def test_chat_catchup_reports_more_pages_and_breaks_timestamp_ties(users, make_ticket, client_for):
    ticket = make_ticket(assignee=users["agent"])
    rows = [ticket.chat_messages.create(sender=users["agent"], content=str(i)) for i in range(6)]
    ticket.chat_messages.update(created_time=timezone.now())
    ids = sorted(str(row.pk) for row in rows)
    client = client_for(users["requester"])
    path = f"{TICKETS}/{ticket.pk}/chat/messages"
    cursor = ids[0]
    for expected, has_more in ((ids[1:3], True), (ids[3:5], True), (ids[5:], False)):
        response = client.get(path, {"after_id": cursor, "limit": 2})
        assert response.status_code == 200, response.data
        data = response.data["data"]
        assert [row["id"] for row in data["results"]] == expected
        assert data["has_more"] is has_more
        cursor = expected[-1]
    older = client.get(path, {"before_id": ids[-1], "limit": 2}).data["data"]
    assert [row["id"] for row in older["results"]] == ids[-3:-1]
    assert older["has_more"] is True


def test_chat_preserves_integrity_error_without_client_id(users, make_ticket):
    agent = users["agent"]
    ticket = make_ticket(status=Status.IN_PROGRESS, assignee=agent)
    error = IntegrityError("write failed")
    with patch.object(TicketChatMessage.objects, "create", side_effect=error), pytest.raises(IntegrityError) as caught:
        send_chat_message(
            Ticket.objects.all(), ticket.pk, agent, TicketAccess.for_user(agent), kind="TEXT", content="测试"
        )
    assert caught.value is error


def test_admin_chat_notifies_both_participants(users, make_ticket, client_for, django_capture_on_commit_callbacks):
    ticket = make_ticket(status=Status.IN_PROGRESS, assignee=users["agent"])
    with patch("tickets.chat_services.notify_users") as notify, django_capture_on_commit_callbacks(execute=True):
        response = client_for(users["admin"]).post(
            f"{TICKETS}/{ticket.pk}/chat/messages", {"content": "请补充截图"}, format="json"
        )
        assert response.status_code == 201, response.data
    notify.assert_called_once()
    assert set(notify.call_args.args[0]) == {users["requester"].pk, users["agent"].pk}


def test_generic_and_cross_owner_uploads_cannot_bind(users, make_ticket, client_for, details):
    user = users["requester"]
    ticket = make_ticket(status=Status.IN_PROGRESS, assignee=users["agent"])
    api = client_for(user)
    generic = UploadFile.objects.create(
        creator=user,
        is_upload=True,
        is_tmp=True,
        filename="generic.png",
        filepath=make_png(),
        filesize=100,
        mime_type="image/png",
    )
    uploaded = client_for(users["agent"]).post(
        f"{TICKETS}/attachments/upload", {"file": make_png()}, format="multipart"
    )
    assert uploaded.status_code == 201, uploaded.data
    for file_pk in (str(generic.pk), uploaded.data["data"]["file_pk"]):
        assert_error(
            api.post(
                TICKETS, {**details, "attachment_ids": [file_pk]}, format="json", HTTP_IDEMPOTENCY_KEY=str(uuid4())
            ),
            400,
        )
        assert_error(
            api.post(f"{TICKETS}/{ticket.pk}/chat/messages", {"kind": "IMAGE", "file_pk": file_pk}, format="json"), 400
        )


def test_video_over_global_limit_can_bind_and_survives_file_cleanup(users, make_ticket, client_for):
    ticket = make_ticket(status=Status.IN_PROGRESS, assignee=users["agent"])
    api = client_for(users["requester"])
    path = f"{TICKETS}/{ticket.pk}/chat"
    data = make_mp4().read().ljust(11 * 1024 * 1024, b"\x00")
    assert get_upload_max_size(users["requester"]) == 10 * 1024 * 1024
    upload = api.post(f"{path}/upload", {"file": SimpleUploadedFile("large.mp4", data)}, format="multipart")
    assert upload.status_code == 201, upload.data
    file_pk = upload.data["data"]["file_pk"]
    assert isinstance(file_pk, str)
    message = api.post(f"{path}/messages", {"kind": "VIDEO", "file_pk": file_pk}, format="json")
    assert message.status_code == 201, message.data
    UploadFile.objects.filter(pk=file_pk).update(created_time=timezone.now() - timedelta(days=2))
    auto_clean_upload_file(keep_days=1)
    assert api.get(message.data["data"]["file_url"], HTTP_RANGE="bytes=0-15").status_code == 206
    assert api.get(message.data["data"]["file_url"], HTTP_RANGE=f"bytes={len(data)}-").status_code == 416


def test_both_upload_routes_share_the_users_media_limit(users, make_ticket, client_for):
    ticket = make_ticket(status=Status.IN_PROGRESS, assignee=users["agent"])
    user = users["requester"]
    api = client_for(user)
    key = f"{TICKET_CACHE_KEY_PREFIX}rate:ticket-media-upload:{user.pk}"
    try:
        for _ in range(29):
            check_rate(user.pk, "ticket-media-upload", 30)
        upload = api.post(f"{TICKETS}/attachments/upload", {"file": make_png()}, format="multipart")
        assert upload.status_code == 201, upload.data
        response = api.post(f"{TICKETS}/{ticket.pk}/chat/upload", {"file": make_png()}, format="multipart")
        assert_error(response, 429)
        assert int(response["Retry-After"]) > 0
    finally:
        cache.delete(key)


def test_historical_handler_can_read_but_cannot_upload_or_send(users, make_ticket, client_for):
    ticket = make_ticket(status=Status.IN_PROGRESS, assignee=users["admin"])
    agent = users["agent"]
    ticket.assignments.create(assignee=agent, started_at=timezone.now(), ended_at=timezone.now())
    api = client_for(agent)
    path = f"{TICKETS}/{ticket.pk}/chat"
    assert api.get(f"{path}/messages").data["data"]["chat_state"] == {"can_send": False, "lock_reason": "READ_ONLY"}
    assert_error(api.post(f"{path}/messages", {"content": "越权发送"}, format="json"), 403)
    assert_error(api.post(f"{path}/upload", {"file": make_png()}, format="multipart"), 403)


def test_chat_upload_requires_send_permission(users, make_ticket):
    ticket = make_ticket(status=Status.IN_PROGRESS, assignee=users["agent"])
    user = users["requester"]
    role = user.roles.get()
    assert role.menu.filter(name="chatUpload:TicketFlowTickets").exists()
    role.menu.remove(Menu.objects.get(name="chatSend:TicketFlowTickets"))
    api = authenticated(user)
    path = f"{TICKETS}/{ticket.pk}"
    state = {"can_send": False, "lock_reason": "READ_ONLY"}
    assert api.get(path).data["data"]["chat_state"] == state
    assert api.get(f"{path}/chat/messages").data["data"]["chat_state"] == state
    before = UploadFile.objects.filter(creator=user).count()
    response = api.post(f"{path}/chat/upload", {"file": make_png()}, format="multipart")
    assert_error(response, 403)
    assert UploadFile.objects.filter(creator=user).count() == before
