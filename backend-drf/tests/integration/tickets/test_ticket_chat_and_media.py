from datetime import timedelta
from io import BytesIO
from uuid import uuid4

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from PIL import Image

from identity.models import UserInfo
from tests.integration.tickets.test_ticket_api import assert_error
from tickets.models import Status, Ticket, TicketChatMessage
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
