from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from common.cache.storage import UserTokenRevokedCache
from knowledge.models import ArticleStatus, KnowledgeArticle
from knowledge.services import references_for_text
from notifications.models import MessageContent
from system.models import Menu
from tests.integration.tickets.test_ticket_api import assert_error, authenticated
from tickets.models import Category, Priority, Status, Ticket, TicketSlaAlert
from tickets.tasks import scan_ticket_sla

pytestmark = pytest.mark.django_db
TICKETS = "/api/tickets"
INTERNAL_SESSIONS = "/api/assistant/internal/sessions"


def test_internal_secret_guards_ai_context_and_allows_service_answer_writeback(users, make_ticket, settings):
    settings.TICKETFLOW_INTERNAL_API_SECRET = "test-shared-internal-secret"
    ticket = make_ticket(assignee=users["agent"])
    agent = authenticated(users["agent"])

    assert_error(agent.get(f"{TICKETS}/{ticket.pk}/ai-context"), 403)
    allowed = agent.get(
        f"{TICKETS}/{ticket.pk}/ai-context",
        HTTP_X_INTERNAL_TOKEN="test-shared-internal-secret",
    )
    assert allowed.status_code == 200, allowed.data
    assert allowed.data["data"]["recent_messages"] == []

    employee = authenticated(users["requester"])
    session = employee.post("/api/assistant/sessions", {}, format="json").data["data"]
    assert_error(
        employee.post(f"{INTERNAL_SESSIONS}/{session['pk']}/question", {"message": "VPN"}, format="json"),
        403,
    )
    asked = employee.post(
        f"{INTERNAL_SESSIONS}/{session['pk']}/question",
        {"message": "VPN"},
        format="json",
        HTTP_X_INTERNAL_TOKEN="test-shared-internal-secret",
    )
    assert asked.status_code == 201, asked.data
    user_message_id = asked.data["data"]["user_message_id"]

    # A service-only callback can finish a turn after the user JWT expires.
    service_client = APIClient()
    saved = service_client.post(
        f"{INTERNAL_SESSIONS}/{session['pk']}/answer",
        {
            "user_message_id": user_message_id,
            "content": "请检查网络设置",
            "references": [],
            "status": "complete",
        },
        format="json",
        HTTP_X_INTERNAL_TOKEN="test-shared-internal-secret",
        HTTP_X_INTERNAL_USER_ID=str(users["requester"].pk),
    )
    assert saved.status_code == 200, saved.data
    assert saved.data["data"]["assistant_message_id"]


@pytest.mark.parametrize("user_id", ["0", str(2**63), "9" * 19])
def test_service_answer_rejects_user_ids_outside_bigint_range(settings, user_id):
    with patch("tickets.internal_auth.get_user_model", wraps=get_user_model) as lookup:
        response = APIClient().post(
            f"{INTERNAL_SESSIONS}/{uuid4()}/answer",
            {},
            format="json",
            HTTP_X_INTERNAL_TOKEN=settings.TICKETFLOW_INTERNAL_API_SECRET,
            HTTP_X_INTERNAL_USER_ID=user_id,
        )
    assert_error(response, 401)
    lookup.assert_not_called()


def test_internal_reads_never_accept_service_identity_or_revoked_jwt(users, make_ticket, settings):
    user = users["requester"]
    employee = authenticated(user)
    session_id = employee.post("/api/assistant/sessions", {}, format="json").data["data"]["pk"]
    path = f"{INTERNAL_SESSIONS}/{session_id}"
    service = {
        "HTTP_X_INTERNAL_TOKEN": settings.TICKETFLOW_INTERNAL_API_SECRET,
        "HTTP_X_INTERNAL_USER_ID": str(user.pk),
    }
    payload = {"message": "VPN"}
    unauthenticated = APIClient()
    assert_error(unauthenticated.post(f"{path}/question", payload, format="json", **service), 401)
    assert_error(unauthenticated.get(f"{path}/context", **service), 401)
    assert_error(unauthenticated.get(f"{TICKETS}/{make_ticket().pk}/ai-context"), 401)
    revoked = UserTokenRevokedCache(user.pk)
    revoked.set_storage_cache(timezone.now().timestamp())
    try:
        assert_error(employee.post(f"{path}/question", payload, format="json", **service), 401)
        assert_error(employee.get(f"{path}/context", **service), 401)
        assert_error(employee.post(f"{path}/answer", {}, format="json", **service), 401)
    finally:
        revoked.del_storage_cache()
    forged = APIClient(HTTP_AUTHORIZATION="Bearer invalid")
    assert_error(forged.post(f"{path}/question", payload, format="json", **service), 401)


def test_internal_routes_fail_closed_when_secret_is_empty(users, make_ticket, settings):
    employee = authenticated(users["requester"])
    session_id = employee.post("/api/assistant/sessions", {}, format="json").data["data"]["pk"]
    settings.TICKETFLOW_INTERNAL_API_SECRET = " "
    assert_error(employee.get(f"{INTERNAL_SESSIONS}/{session_id}/context", HTTP_X_INTERNAL_TOKEN="anything"), 403)
    ticket = make_ticket(assignee=users["agent"])
    assert_error(authenticated(users["agent"]).get(f"{TICKETS}/{ticket.pk}/ai-context"), 403)


def test_kb_draft_context_requires_unarchived_ticket_and_create_permission(users, make_ticket, client_for):
    agent = users["agent"]
    ticket = make_ticket(status=Status.CLOSED, assignee=users["admin"])
    ticket.assignments.create(assignee=agent, started_at=timezone.now(), ended_at=timezone.now())
    api = client_for(agent)
    path = f"{TICKETS}/{ticket.pk}/ai-context"
    assert_error(api.get(path), 403)
    assert api.get(path, {"purpose": "kb-draft"}).status_code == 200
    grant = Menu.objects.get(name="create:TicketFlowKnowledge")
    role = agent.roles.get()
    role.menu.remove(grant)
    assert_error(api.get(path, {"purpose": "kb-draft"}), 403)
    role.menu.add(grant)
    KnowledgeArticle.objects.create(title="已有转存", source_ticket=ticket)
    assert_error(api.get(path, {"purpose": "kb-draft"}), 403)


def test_ai_context_rejects_unknown_purpose_and_accepts_empty_purpose(users, make_ticket):
    agent = users["agent"]
    ticket = make_ticket(assignee=agent)
    api = authenticated(agent, internal=True)
    path = f"{TICKETS}/{ticket.pk}/ai-context"
    response = api.get(path, {"purpose": "unknown"})
    assert_error(response, 400)
    assert "purpose" in response.data["detail"]
    assert api.get(path, {"purpose": ""}).status_code == 200


def test_save_ai_metadata_blocks_closed_and_recalculates_sla_on_priority_change(users, make_ticket, client_for):
    ticket = make_ticket(priority=Priority.P3, assignee=users["agent"])
    original_due = ticket.sla_due_at
    agent = client_for(users["agent"])

    escalated = agent.post(
        f"{TICKETS}/{ticket.pk}/ai-metadata",
        {"version": ticket.version, "summary": "紧急故障", "tags": ["故障"], "priority": Priority.P0},
        format="json",
    )
    assert escalated.status_code == 200, escalated.data
    ticket.refresh_from_db()
    assert ticket.priority == Priority.P0
    assert ticket.sla_due_at == original_due - timedelta(hours=70)

    closed = make_ticket(status=Status.CLOSED, assignee=users["agent"])
    admin = client_for(users["admin"])
    blocked = admin.post(
        f"{TICKETS}/{closed.pk}/ai-metadata",
        {"version": closed.version, "summary": "覆写", "tags": []},
        format="json",
    )
    assert_error(blocked, 409)


def test_short_ticket_number_format_and_sla_scan_sends_notification(
    users, client_for, details, django_capture_on_commit_callbacks
):
    requester = client_for(users["requester"])
    created = requester.post(TICKETS, details, format="json", HTTP_IDEMPOTENCY_KEY=str(uuid4()))
    assert created.status_code == 201, created.data
    number = created.data["data"]["number"]
    assert number.startswith("TF-") and len(number) == 18

    ticket = Ticket.objects.get(pk=created.data["data"]["pk"])
    Ticket.objects.filter(pk=ticket.pk).update(sla_due_at=timezone.now() - timedelta(minutes=2))
    before = MessageContent.objects.count()
    with django_capture_on_commit_callbacks(execute=True):
        assert scan_ticket_sla.run() == 1
        assert scan_ticket_sla.run() == 0
    assert TicketSlaAlert.objects.filter(ticket=ticket, kind=TicketSlaAlert.Kind.OVERDUE).count() == 1
    assert MessageContent.objects.count() > before


def test_chinese_rag_natural_question_and_followup_history_retrieval(users, client_for):
    password_guide = KnowledgeArticle.objects.create(
        title="账号密码重置指南",
        body_markdown="如忘记登录密码，请联系 IT 管理员重置密码或使用自助找回入口。",
        category=Category.ACCOUNT,
        status=ArticleStatus.PUBLISHED,
    )
    vpn_guide = KnowledgeArticle.objects.create(
        title="VPN 691 报错排障手册",
        body_markdown="VPN 客户端报错 691 通常是域账号密码过期，Windows 和 Mac 均需重新登录。",
        category=Category.NETWORK,
        status=ArticleStatus.PUBLISHED,
    )
    hits = references_for_text("我的登录密码忘记了怎么重置")
    assert hits and hits[0]["article_id"] == str(password_guide.pk)

    employee = client_for(users["requester"])
    session_id = employee.post("/api/assistant/sessions", {}, format="json").data["data"]["pk"]
    turn1 = employee.post(
        f"{INTERNAL_SESSIONS}/{session_id}/question",
        {"message": "VPN 报错 691 怎么办"},
        format="json",
    )
    assert turn1.status_code == 201
    assert turn1.data["data"]["references"][0]["article_id"] == str(vpn_guide.pk)

    turn2 = employee.post(
        f"{INTERNAL_SESSIONS}/{session_id}/question",
        {"message": "Mac 上也是这样吗？"},
        format="json",
    )
    assert turn2.status_code == 201
    assert turn2.data["data"]["references"][0]["article_id"] == str(vpn_guide.pk)
