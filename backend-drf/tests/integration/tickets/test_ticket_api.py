from uuid import uuid4

import pytest
from django.core.management import call_command
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from identity.models import DeptInfo, UserInfo, UserRole
from knowledge.models import ArticleStatus, KnowledgeArticle
from tickets.models import Status, Ticket, Visibility
from tickets.policy import ADMIN_ROLE, AGENT_ROLE
from tickets.services import NewTicket


def authenticated(user: UserInfo) -> APIClient:
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")
    return client


@pytest.mark.django_db
def test_ticket_knowledge_and_data_scope(details: NewTicket, seed_creator_user: None) -> None:
    call_command("load_init_json", verbosity=0)
    support = DeptInfo.objects.get(code="ticketflow_support")
    owner = UserInfo.objects.create_user(username="ticket-owner")
    outsider = UserInfo.objects.create_user(username="ticket-outsider")
    staff = UserInfo.objects.create_user(username="ticket-agent", dept=support)
    admin = UserInfo.objects.create_user(username="ticket-admin")
    default_role = UserRole.objects.get(code="default")
    owner.roles.add(default_role)
    outsider.roles.add(default_role)
    staff.roles.add(UserRole.objects.get(code=AGENT_ROLE))
    admin.roles.add(UserRole.objects.get(code=ADMIN_ROLE))
    owner_api, outsider_api, staff_api, admin_api = map(authenticated, (owner, outsider, staff, admin))

    key = str(uuid4())
    payload = owner_api.post("/api/tickets", details, format="json", HTTP_IDEMPOTENCY_KEY=key)
    assert payload.status_code == 201, payload.data
    assert payload.data["data"]["category"] == details["category"]
    ticket_id = payload.data["data"]["pk"]
    replay = owner_api.post("/api/tickets", details, format="json", HTTP_IDEMPOTENCY_KEY=key)
    assert replay.status_code == 200
    assert replay.data["data"]["pk"] == ticket_id
    resource = f"/api/tickets/{ticket_id}"
    assert outsider_api.get(resource).status_code == 404
    assert outsider_api.get("/api/tickets").data["data"]["total"] == 0

    assert (
        staff_api.post(
            f"{resource}/comments", {"body": "内部回复内容", "visibility": Visibility.INTERNAL}, format="json"
        ).status_code
        == 201
    )
    assert (
        owner_api.post(
            f"{resource}/comments", {"body": "越权备注", "visibility": Visibility.INTERNAL}, format="json"
        ).status_code
        == 403
    )
    assert len(owner_api.get(resource).data["data"]["timeline"]["results"]) == 1
    assert len(staff_api.get(f"{resource}/timeline").data["data"]["results"]) == 2

    articles = "/api/knowledge/articles"
    article_input = {
        "title": "VPN 连接失败处理",
        "body_markdown": "先检查 VPN 连接状态",
        "category": details["category"],
        "source_ticket_id": ticket_id,
    }
    early = staff_api.post(articles, article_input, format="json")
    assert early.status_code == 409
    Ticket.objects.filter(pk=ticket_id).update(status=Status.CLOSED)
    draft = staff_api.post(articles, article_input, format="json")
    assert draft.status_code == 201, draft.data
    article_id = draft.data["data"]["pk"]
    assert staff_api.post(articles, article_input, format="json").status_code == 409
    assert outsider_api.get(f"{articles}/{article_id}").status_code == 404
    assert (
        staff_api.patch(f"{articles}/{article_id}", {"status": ArticleStatus.PUBLISHED}, format="json").status_code
        == 403
    )
    assert (
        admin_api.patch(f"{articles}/{article_id}", {"status": ArticleStatus.PUBLISHED}, format="json").status_code
        == 200
    )
    detail = outsider_api.get(f"{articles}/{article_id}")
    assert detail.data["data"]["body_markdown"] == article_input["body_markdown"]
    assert detail.data["data"]["source_ticket_id"] is None
    assert KnowledgeArticle.objects.get(pk=article_id).view_count == 1

    assert owner_api.get(f"{resource}/ai-context").status_code == 403
    result = staff_api.get(f"{resource}/ai-context")
    assert result.status_code == 200, result.data
    assert result.data["data"]["references"][0]["article_id"] == article_id

    exported = admin_api.post("/api/tickets/export-async", {"type": "csv", "status": Status.CLOSED}, format="json")
    assert exported.status_code == 200, exported.data
    record_id = exported.data["data"]["record_id"]
    downloaded = admin_api.get(f"/api/task/exports/{record_id}/download")
    assert downloaded.status_code == 200
    assert details["title"] in b"".join(downloaded.streaming_content).decode("utf-8-sig")
    assert outsider_api.get(f"/api/task/exports/{record_id}/download").status_code == 403
