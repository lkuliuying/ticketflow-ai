import json
from pathlib import Path

import pytest
from django.urls import resolve
from django.utils import timezone
from jsonschema import Draft202012Validator

from identity.models import DeptInfo, UserInfo, UserRole
from knowledge.models import ArticleStatus, KnowledgeArticle
from system.models import Menu
from tests.integration.tickets.test_ticket_api import authenticated
from tickets.models import Category, Priority, Status, Ticket, TicketAssignment, Visibility
from tickets.policy import ADMIN_ROLE, AGENT_ROLE

pytestmark = pytest.mark.django_db
ARTICLES = "/api/knowledge/articles"
SCHEMA = json.loads(
    (Path(__file__).resolve().parents[3] / "docs/schema/ticketflow.schema.json").read_text(encoding="utf-8")
)


def validate(data: object, definition: str) -> None:
    Draft202012Validator({**SCHEMA, "$ref": f"#/$defs/{definition}"}).validate(data)


@pytest.fixture
def ticket(users: dict[str, UserInfo]) -> Ticket:
    return Ticket.objects.create(
        number="TF-VIEWER",
        title="网络问题",
        description="连接失败",
        category=Category.NETWORK,
        priority=Priority.P1,
        submitter=users["requester"],
        department=users["agent"].dept,
        assignee=users["agent"],
        sla_due_at=timezone.now(),
    )


@pytest.mark.parametrize(
    ("role", "can_handle", "has_assignment_grants"),
    [
        ("requester", False, False),
        ("agent", True, False),
        ("admin", True, True),
    ],
)
@pytest.mark.parametrize("status", [Status.IN_PROGRESS, Status.CLOSED])
def test_ticket_viewer_matches_role_and_status(users, make_ticket, role, can_handle, has_assignment_grants, status):
    ticket = make_ticket(status=status, assignee=users["agent"])
    api = authenticated(users[role])
    resource = f"/api/tickets/{ticket.pk}"
    response = api.get(resource)
    assert response.status_code == 200, response.data
    data = response.data["data"]
    assert data["viewer"] == {
        "can_handle": can_handle,
        "can_assign": has_assignment_grants and status != Status.CLOSED,
        "can_reply": True,
        "can_comment_internal": can_handle,
        "can_archive": can_handle and status == Status.CLOSED,
        "can_return": role == "agent" and status != Status.CLOSED,
        "read_only": False,
    }
    validate(data["viewer"], "ticketViewer")
    if status == Status.CLOSED:
        KnowledgeArticle.objects.create(title="转存草稿", creator=users["agent"], source_ticket=ticket)
        assert api.get(resource).data["data"]["viewer"]["can_archive"] is False
    else:
        assert tuple(data["available_transitions"]) == ((Status.PENDING_VERIFY,) if can_handle else ())


@pytest.mark.parametrize("is_superuser", [False, True])
def test_ticket_viewer_assignment_requires_both_menu_permissions(users, ticket, api_client, is_superuser):
    if is_superuser:
        user = UserInfo.objects.create_user(username="viewer-superuser", is_superuser=True)
    else:
        role = UserRole.objects.get(code=ADMIN_ROLE)
        role.menu.remove(Menu.objects.get(name="assignees:TicketFlowTickets"))
        user = users["admin"]
    api_client.force_authenticate(user=user)
    resource = f"/api/tickets/{ticket.pk}"
    detail = api_client.get(resource)
    assert detail.status_code == 200, detail.data
    assert detail.data["data"]["viewer"]["can_handle"] is True
    assert detail.data["data"]["viewer"]["can_assign"] is is_superuser
    assert api_client.get(f"{resource}/assignees").status_code == (200 if is_superuser else 403)


@pytest.mark.parametrize("role", ["requester", "agent"])
def test_ticket_viewer_comment_capabilities_require_menu_permission(users, ticket, role):
    user = users[role]
    user.roles.get().menu.remove(Menu.objects.get(name="comments:TicketFlowTickets"))
    api = authenticated(user)
    resource = f"/api/tickets/{ticket.pk}"

    detail = api.get(resource)
    assert detail.status_code == 200, detail.data
    viewer = detail.data["data"]["viewer"]
    assert viewer["can_handle"] is (role == "agent")
    assert (viewer["can_reply"], viewer["can_comment_internal"]) == (False, False)

    for visibility in (Visibility.PUBLIC, Visibility.INTERNAL):
        response = api.post(f"{resource}/comments", {"body": "工单跟进", "visibility": visibility}, format="json")
        assert response.status_code == 403, response.data
    assert not ticket.comments.exists()


def test_ticket_viewer_respects_action_grants_and_submitter_only_scope(users, ticket):
    role = UserRole.objects.get(code=AGENT_ROLE)
    role.menu.remove(Menu.objects.get(name="create:TicketFlowKnowledge"))
    role.menu.add(*Menu.objects.filter(name__in=["assign:TicketFlowTickets", "assignees:TicketFlowTickets"]))
    api = authenticated(users["agent"])
    resource = f"/api/tickets/{ticket.pk}"
    assert api.get(resource).data["data"]["viewer"]["can_assign"] is False
    blocked = api.post(f"{resource}/assign", {"assignee_id": None, "version": ticket.version}, format="json")
    assert blocked.status_code == 403
    ticket.status = Status.CLOSED
    ticket.save(update_fields=["status"])
    viewer = api.get(resource).data["data"]["viewer"]
    assert viewer == {
        "can_handle": True,
        "can_assign": False,
        "can_reply": True,
        "can_comment_internal": True,
        "can_archive": False,
        "can_return": False,
        "read_only": False,
    }
    ticket.submitter = users["agent"]
    ticket.assignee = None
    ticket.save(update_fields=["submitter", "assignee"])
    viewer = api.get(resource).data["data"]["viewer"]
    assert viewer == {
        "can_handle": False,
        "can_assign": False,
        "can_reply": True,
        "can_comment_internal": False,
        "can_archive": False,
        "can_return": False,
        "read_only": False,
    }


def test_ticket_viewer_cannot_archive_without_knowledge_app(users, ticket, settings):
    ticket.status = Status.CLOSED
    ticket.save(update_fields=["status"])
    resource = f"/api/tickets/{ticket.pk}"
    # 初始化路由后再临时移除应用，避免后续用例沿用缺失知识库路由的 URLConf。
    resolve(resource)
    settings.INSTALLED_APPS = [app for app in settings.INSTALLED_APPS if app != "knowledge"]
    response = authenticated(users["admin"]).get(resource)
    assert response.status_code == 200, response.data
    assert response.data["data"]["viewer"]["can_archive"] is False


def grant_assignment(user: UserInfo) -> None:
    role = UserRole.objects.create(code="assignment_delegate", name="指派授权")
    role.menu.add(*Menu.objects.filter(name__in=["assign:TicketFlowTickets", "assignees:TicketFlowTickets"]))
    user.roles.add(role)


def test_assignees_filter_skill_group_roles_activity_and_search(users, ticket):
    other = DeptInfo.objects.create(code="other-support", name="其他支持")
    external = UserInfo.objects.create_user(username="candidate-external", dept=other)
    external.roles.add(UserRole.objects.get(code=AGENT_ROLE))
    inactive = UserInfo.objects.create_user(username="candidate-inactive", dept=users["agent"].dept, is_active=False)
    inactive.roles.add(UserRole.objects.get(code=AGENT_ROLE))
    department_role = UserRole.objects.create(code="disabled-handler", name="已停用客服", is_active=False)
    disabled = UserInfo.objects.create_user(username="candidate-disabled", dept=users["agent"].dept)
    disabled.roles.add(department_role)
    inherited_dept = DeptInfo.objects.create(code="inherited", name="部门授权")
    inherited_dept.roles.add(UserRole.objects.get(code=AGENT_ROLE))
    inherited = UserInfo.objects.create_user(username="candidate-inherited", dept=inherited_dept)
    users["agent"].nickname = "客服昵称"
    users["agent"].save(update_fields=["nickname"])
    api = authenticated(users["admin"])
    resource = f"/api/tickets/{ticket.pk}/assignees"
    response = api.get(resource)
    assert response.status_code == 200, response.data
    rows = response.data["data"]
    validate(rows, "ticketAssignees")
    ids = {row["pk"] for row in rows}
    assert users["requester"].pk not in ids
    assert inactive.pk not in ids and disabled.pk not in ids
    assert ids == {users["agent"].pk, external.pk, inherited.pk}
    filtered = api.get(resource, {"department_id": other.pk}).data["data"]
    assert [row["pk"] for row in filtered] == [external.pk]
    assert api.get(resource, {"department_id": "invalid"}).status_code == 400
    searched = api.get(resource, {"q": "客服昵称"}).data["data"]
    assert searched == [
        {"pk": users["agent"].pk, "username": "viewer-agent", "nickname": "客服昵称", "department_name": "工单支持组"}
    ]
    assert api.get(resource, {"q": "no-match"}).data["data"] == []
    assigned = api.post(
        f"/api/tickets/{ticket.pk}/assign", {"assignee_id": external.pk, "version": ticket.version}, format="json"
    )
    assert assigned.status_code == 200, assigned.data


def test_assignees_are_unique_bounded_and_stably_ordered(users, ticket):
    role = UserRole.objects.get(code=AGENT_ROLE)
    for index in range(23):
        candidate = UserInfo.objects.create_user(username=f"candidate-{index:02}", dept=users["agent"].dept)
        candidate.roles.add(role, UserRole.objects.get(code=ADMIN_ROLE))
    response = authenticated(users["admin"]).get(f"/api/tickets/{ticket.pk}/assignees", {"q": "candidate-"})
    assert response.status_code == 200, response.data
    rows = response.data["data"]
    assert len(rows) == len({row["pk"] for row in rows}) == 20
    assert [row["username"] for row in rows] == [f"candidate-{index:02}" for index in range(20)]


def test_assignees_exclude_inactive_roles_and_superusers(users, ticket):
    agent_role = UserRole.objects.get(code=AGENT_ROLE)
    agent_role.is_active = False
    agent_role.save(update_fields=["is_active"])
    superuser = UserInfo.objects.create_user(username="candidate-superuser", is_superuser=True)
    response = authenticated(users["admin"]).get(f"/api/tickets/{ticket.pk}/assignees")
    assert response.status_code == 200, response.data
    rows = response.data["data"]
    assert users["agent"].pk not in {row["pk"] for row in rows}
    assert superuser.pk not in {row["pk"] for row in rows}


def test_assignees_require_assignment_and_handling_and_hide_invisible_ticket(users, ticket):
    grant_assignment(users["agent"])
    resource = f"/api/tickets/{ticket.pk}"
    ticket.assignee = None
    ticket.save(update_fields=["assignee"])
    api = authenticated(users["agent"])
    assert api.get(resource).status_code == 404
    assert api.get(f"{resource}/assignees").status_code == 404
    ticket.submitter = users["agent"]
    ticket.save(update_fields=["submitter"])
    assert api.get(f"{resource}/assignees").status_code == 403
    ticket.assignee = users["agent"]
    ticket.save(update_fields=["assignee"])
    users["agent"].dept = None
    users["agent"].save(update_fields=["dept"])
    assert api.get(f"{resource}/assignees").status_code == 403


def test_assignees_permission_does_not_grant_assignment(users, ticket):
    role = UserRole.objects.get(code=AGENT_ROLE)
    role.menu.add(Menu.objects.get(name="assignees:TicketFlowTickets"))
    response = authenticated(users["agent"]).get(f"/api/tickets/{ticket.pk}/assignees")
    assert response.status_code == 403


@pytest.mark.parametrize(
    ("role", "status", "detail_statuses", "patch_statuses"),
    [
        ("requester", ArticleStatus.DRAFT, (200, 404), (403, 403)),
        ("requester", ArticleStatus.PUBLISHED, (200, 200), (403, 403)),
        ("requester", ArticleStatus.ARCHIVED, (404, 404), (403, 403)),
        ("agent", ArticleStatus.DRAFT, (200, 404), (200, 404)),
        ("agent", ArticleStatus.PUBLISHED, (200, 200), (403, 403)),
        ("agent", ArticleStatus.ARCHIVED, (404, 404), (404, 404)),
        ("admin", ArticleStatus.DRAFT, (200, 200), (200, 200)),
        ("admin", ArticleStatus.PUBLISHED, (200, 200), (200, 200)),
        ("admin", ArticleStatus.ARCHIVED, (200, 200), (200, 200)),
    ],
)
def test_article_permissions_by_status(users, ticket, client_for, role, status, detail_statuses, patch_statuses):
    own = KnowledgeArticle.objects.create(title="本人文章", creator=users[role], status=status)
    other = KnowledgeArticle.objects.create(
        title="他人文章",
        creator=users["requester" if role == "agent" else "agent"],
        status=status,
        source_ticket=ticket,
    )
    api = client_for(users[role])
    admin = role == "admin"
    visible = {
        str(article.pk)
        for article, detail_status in zip((own, other), detail_statuses, strict=True)
        if detail_status == 200
    }

    response = api.get(ARTICLES, {"status": status})
    assert response.status_code == 200, response.data
    page = response.data["data"]
    assert page["total"] == len(visible)
    assert {row["pk"] for row in page["results"]} == visible
    assert all("source_ticket_id" not in row for row in page["results"])
    assert page["can_create_standalone"] is admin
    validate(page, "articleListCapabilities")
    empty = api.get(ARTICLES, {"q": "does-not-exist"}).data["data"]
    assert empty["results"] == [] and empty["can_create_standalone"] is admin

    for article, detail_status, patch_status in zip((own, other), detail_statuses, patch_statuses, strict=True):
        resource = f"{ARTICLES}/{article.pk}"
        detail = api.get(resource)
        assert detail.status_code == detail_status, detail.data
        if detail_status == 200:
            data = detail.data["data"]
            assert data["viewer"] == {"can_edit": patch_status == 200, "can_publish": admin}
            validate(data["viewer"], "articleViewer")
            assert data["source_ticket_id"] == (str(ticket.pk) if admin and article == other else None)

        original_title = article.title
        updated = api.patch(resource, {"title": "修改后的标题"}, format="json")
        assert updated.status_code == patch_status, updated.data
        if patch_status == 200:
            assert updated.data["data"]["title"] == "修改后的标题"
        article.refresh_from_db()
        assert article.title == ("修改后的标题" if patch_status == 200 else original_title)


def test_agent_archives_only_handled_closed_tickets_and_cannot_publish(users, make_ticket, client_for, details):
    api = client_for(users["agent"])
    foreign_dept = DeptInfo.objects.create(code="other-support", name="其他部门")
    invisible = make_ticket(department=foreign_dept, status=Status.CLOSED)
    submitter_only = make_ticket(users["agent"], department=foreign_dept, status=Status.CLOSED)
    opened = make_ticket(assignee=users["agent"])
    closed = make_ticket(status=Status.CLOSED)
    now = timezone.now()
    TicketAssignment.objects.create(
        ticket=closed, assignee=users["agent"], started_at=now, ended_at=now, end_reason="CLOSED_OUT"
    )
    values = {"title": "VPN 连接失败处理", "body_markdown": "先检查 VPN 连接状态", "category": details["category"]}

    for ticket, expected in ((invisible, 404), (submitter_only, 403), (opened, 409)):
        denied = api.post(ARTICLES, {**values, "source_ticket_id": str(ticket.pk)}, format="json")
        assert denied.status_code == expected, denied.data
    assert not KnowledgeArticle.objects.exists()

    payload = {**values, "source_ticket_id": str(closed.pk)}
    created = api.post(ARTICLES, payload, format="json")
    assert created.status_code == 201, created.data
    article = created.data["data"]
    assert article["status"] == ArticleStatus.DRAFT
    assert article["source_ticket_id"] == str(closed.pk)
    duplicate = api.post(ARTICLES, payload, format="json")
    assert duplicate.status_code == 409, duplicate.data
    assert KnowledgeArticle.objects.filter(source_ticket=closed).count() == 1

    resource = f"{ARTICLES}/{article['pk']}"
    assert api.get(resource).data["data"]["source_ticket_id"] == str(closed.pk)
    publish = {"status": ArticleStatus.PUBLISHED}
    assert api.patch(resource, publish, format="json").status_code == 403
    admin = client_for(users["admin"])
    assert admin.patch(resource, publish, format="json").status_code == 200
    assert api.get(resource).data["data"]["source_ticket_id"] == str(closed.pk)


def test_article_capabilities_respect_missing_action_grants(users):
    article = KnowledgeArticle.objects.create(title="知识", creator=users["agent"])
    role = UserRole.objects.get(code=ADMIN_ROLE)
    role.menu.remove(*Menu.objects.filter(name__in=["partialUpdate:TicketFlowKnowledge", "create:TicketFlowKnowledge"]))
    api = authenticated(users["admin"])
    response = api.get(f"{ARTICLES}/{article.pk}")
    assert response.data["data"]["viewer"] == {"can_edit": False, "can_publish": False}
    assert api.get(ARTICLES).data["data"]["can_create_standalone"] is False


def test_only_published_article_detail_counts_views(users, api_client):
    api_client.force_authenticate(user=users["admin"])
    article = KnowledgeArticle.objects.create(title="知识", creator=users["agent"], view_count=4)
    resource = f"{ARTICLES}/{article.pk}"
    assert api_client.get(resource).data["data"]["view_count"] == 4
    assert (
        api_client.patch(resource, {"status": ArticleStatus.PUBLISHED}, format="json").data["data"]["view_count"] == 4
    )
    assert api_client.get(ARTICLES).data["data"]["results"][0]["view_count"] == 4
    assert api_client.get(resource).data["data"]["view_count"] == 5
    assert api_client.get(resource).data["data"]["view_count"] == 6
    assert api_client.patch(resource, {"status": ArticleStatus.ARCHIVED}, format="json").data["data"]["view_count"] == 6
    assert api_client.get(resource).data["data"]["view_count"] == 6
    article.refresh_from_db()
    assert article.view_count == 6


def test_ticket_search_fields_use_localized_labels_and_sla_choices(users, api_client):
    api_client.force_authenticate(user=users["admin"])
    response = api_client.get("/api/tickets/search-fields")
    assert response.status_code == 200, response.data
    fields = {field["key"]: field for field in response.data["data"]}
    assert fields["assignee_id"]["label"] == "处理人"
    assert fields["department_id"]["label"] == "所属技能组"
    assert fields["sla"]["label"] == "SLA 状态"
    assert fields["q"]["label"] == "关键字"
    assert {choice["value"]: choice["label"] for choice in fields["sla"]["choices"] if choice["value"]} == {
        "ON_TRACK": "正常",
        "DUE_SOON": "即将超时",
        "OVERDUE": "已超时",
        "MET": "按时完成",
    }


def test_ticketflow_directory_contains_visible_pages_in_order(users):
    directory = Menu.objects.get(name="TicketFlow")
    assert directory.menu_type == Menu.MenuChoices.DIRECTORY
    children = list(Menu.objects.filter(parent=directory).select_related("meta").order_by("rank"))
    assert [page.component for page in children] == ["ticketflow/tickets/index", "ticketflow/knowledge/index"]
    assert all(page.meta.is_show_menu for page in children)
    for user in users.values():
        assert user.roles.filter(menu=directory).exists()
