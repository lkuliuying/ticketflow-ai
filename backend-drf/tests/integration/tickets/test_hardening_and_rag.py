from datetime import timedelta
from uuid import uuid4

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from knowledge.models import ArticleStatus, KnowledgeArticle
from knowledge.services import references_for_text
from notifications.models import MessageContent
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

    # Simulate an expired or missing user JWT while FastAPI writes back with service credentials.
    service_client = APIClient()
    service_client.credentials(HTTP_AUTHORIZATION="Bearer expired-invalid-token")
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
