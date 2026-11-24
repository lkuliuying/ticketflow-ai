import csv
import io
from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from uuid import uuid4

import pytest
from django.core.cache import cache
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from common.cache.storage import UserTokenRevokedCache
from identity.models import DeptInfo, UserInfo
from knowledge.models import ArticleStatus, KnowledgeArticle
from system.models import FieldPermission, Menu
from system.tasks import async_export_data_task
from task.models.export import ExportRecord
from tickets.cache import TICKET_CACHE_KEY_PREFIX, WINDOW_SECONDS, request_key
from tickets.models import (
    Priority,
    Status,
    Ticket,
    TicketAssignment,
    TicketComment,
    TicketCreateRequest,
    TicketLog,
    Visibility,
)

pytestmark = pytest.mark.django_db
TICKETS = "/api/tickets"


def authenticated(user: UserInfo) -> APIClient:
    token = RefreshToken.for_user(user).access_token
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return client


def assert_error(response, status):
    assert response.status_code == status, response.content
    payload = response.json()
    assert payload["code"] != 1000
    assert isinstance(payload["detail"], str) and payload["detail"]


def test_user_revocation_rejects_old_token_and_accepts_new_token(users):
    user = users["requester"]
    issued_at = datetime.now(UTC).replace(microsecond=0)
    revoked_at = issued_at - timedelta(seconds=1)
    with patch("rest_framework_simplejwt.tokens.aware_utcnow", return_value=revoked_at):
        old_client = authenticated(user)
    assert old_client.get(TICKETS).status_code == 200

    UserTokenRevokedCache(user.pk).set_storage_cache(revoked_at.timestamp())

    assert_error(old_client.get(TICKETS), 401)
    with patch("rest_framework_simplejwt.tokens.aware_utcnow", return_value=issued_at):
        new_client = authenticated(user)
    assert new_client.get(TICKETS).status_code == 200


@pytest.mark.parametrize("cache_result", [False, True], ids=["database-replay", "redis-replay"])
def test_create_requires_idempotency_key_and_replays_same_request(
    users, client_for, details, django_capture_on_commit_callbacks, cache_result
):
    user = users["requester"]
    api = client_for(user)
    assert_error(api.post(TICKETS, details, format="json"), 400)
    assert not Ticket.objects.exists()
    assert not TicketCreateRequest.objects.exists()

    headers = {"HTTP_IDEMPOTENCY_KEY": str(uuid4())}
    with django_capture_on_commit_callbacks(execute=cache_result):
        created = api.post(TICKETS, details, format="json", **headers)
    assert created.status_code == 201, created.data
    original = created.data["data"]
    assert original["category"] == details["category"]
    assert original["title"] == details["title"]
    request_record = TicketCreateRequest.objects.get()
    assert (cache.get(request_key(user.pk, request_record.key_hash)) is not None) is cache_result

    replayed = api.post(TICKETS, details, format="json", **headers)
    assert replayed.status_code == 200, replayed.data
    assert replayed.data["data"] == original
    conflict = api.post(TICKETS, {**details, "title": "不同的工单"}, format="json", **headers)
    assert_error(conflict, 409)
    assert list(Ticket.objects.values_list("pk", flat=True)) == [request_record.ticket_id]
    assert str(request_record.ticket_id) == original["pk"]


def test_transition_distinguishes_hidden_ticket_missing_action_and_stale_version(users, make_ticket, client_for):
    ticket = make_ticket(assignee=users["agent"])
    resource = f"{TICKETS}/{ticket.pk}"
    owner = client_for(users["requester"])
    agent = client_for(users["agent"])
    outsider = UserInfo.objects.create_user(username="outside-requester")
    outsider.roles.set(users["requester"].roles.all())
    other = client_for(outsider)
    payload = {"target_status": Status.IN_PROGRESS, "version": ticket.version}

    assert_error(other.get(resource), 404)
    assert other.get(TICKETS).data["data"]["total"] == 0
    assert_error(other.post(f"{resource}/transition", payload, format="json"), 404)
    assert owner.get(resource).status_code == 200
    assert_error(owner.post(f"{resource}/transition", payload, format="json"), 403)

    changed = agent.post(f"{resource}/transition", payload, format="json")
    assert changed.status_code == 200, changed.data
    assert changed.data["data"]["version"] == ticket.version + 1
    assert_error(
        agent.post(f"{resource}/transition", {**payload, "target_status": Status.PENDING_VERIFY}, format="json"), 409
    )
    ticket.refresh_from_db()
    assert ticket.status == Status.IN_PROGRESS
    assert ticket.version == changed.data["data"]["version"]
    assert list(ticket.logs.values_list("action", flat=True)) == ["TRANSITION"]


@pytest.mark.parametrize("clear_assignee", [False, True], ids=["reassign", "unassign"])
def test_closed_ticket_rejects_assignment(users, make_ticket, client_for, clear_assignee):
    ticket = make_ticket(status=Status.PENDING_VERIFY, assignee=users["agent"])
    resource = f"{TICKETS}/{ticket.pk}"
    requester = client_for(users["requester"])
    closed = requester.post(
        f"{resource}/transition", {"target_status": Status.CLOSED, "version": ticket.version}, format="json"
    )
    assert closed.status_code == 200, closed.data
    version = closed.data["data"]["version"]

    admin = client_for(users["admin"])
    assignee_id = None if clear_assignee else users["admin"].pk
    response = admin.post(f"{resource}/assign", {"assignee_id": assignee_id, "version": version}, format="json")
    assert_error(response, 409)
    assert response.json()["detail"] == "已关闭的工单不能指派"
    ticket.refresh_from_db()
    assert ticket.assignee_id == users["agent"].pk
    assert ticket.version == version
    assert not ticket.logs.filter(action="ASSIGN").exists()


@pytest.mark.parametrize("status", [Status.IN_PROGRESS, Status.CLOSED])
def test_ticket_submitter_can_reply_at_either_status(users, make_ticket, client_for, status):
    ticket = make_ticket(status=status)
    requester = client_for(users["requester"])
    endpoint = f"{TICKETS}/{ticket.pk}/comments"
    response = requester.post(endpoint, {"body": "补充问题描述", "visibility": Visibility.PUBLIC}, format="json")
    assert response.status_code == 201, response.data
    assert ticket.comments.get().author_id == users["requester"].pk


def test_comments_preserve_first_staff_response_and_hide_internal_activity(users, make_ticket, client_for):
    ticket = make_ticket(assignee=users["agent"])
    resource = f"{TICKETS}/{ticket.pk}"
    agent = client_for(users["agent"])
    requester = client_for(users["requester"])

    def comment(api, body, visibility):
        return api.post(f"{resource}/comments", {"body": body, "visibility": visibility}, format="json")

    assert_error(comment(requester, "越权备注", Visibility.INTERNAL), 403)
    requester_reply = comment(requester, "补充问题描述", Visibility.PUBLIC)
    internal = comment(agent, "内部排查记录", Visibility.INTERNAL)
    assert requester_reply.status_code == internal.status_code == 201
    ticket.refresh_from_db()
    assert ticket.first_response_at is None

    replied = comment(agent, "首次对外回复", Visibility.PUBLIC)
    assert replied.status_code == 201, replied.data
    first_response = TicketComment.objects.get(pk=replied.data["data"]["id"]).created_time
    ticket.refresh_from_db()
    assert ticket.first_response_at == first_response
    assert comment(agent, "后续答复", Visibility.PUBLIC).status_code == 201
    ticket.refresh_from_db()
    assert ticket.first_response_at == first_response

    metadata = agent.post(
        f"{resource}/ai-metadata", {"version": ticket.version, "summary": "内部建议", "tags": []}, format="json"
    )
    assert metadata.status_code == 200, metadata.data
    internal_log = str(ticket.logs.get(action="AI_METADATA", internal=True).pk)
    hidden = {str(internal.data["data"]["id"]), internal_log}

    for endpoint, data_key in ((resource, "timeline"), (f"{resource}/timeline", None)):
        for api, is_handler in ((requester, False), (agent, True)):
            response = api.get(endpoint)
            assert response.status_code == 200, response.data
            data = response.json()["data"]
            timeline = data[data_key] if data_key else data
            ids = {row["id"] for row in timeline["results"]}
            assert ids & hidden == (hidden if is_handler else set())
            assert timeline["total"] == (5 if is_handler else 3)
            assert str(replied.data["data"]["id"]) in ids


def test_timeline_first_page_matches_full_pagination_across_timestamp_ties(users, make_ticket, client_for):
    ticket = make_ticket(assignee=users["agent"])
    actor = users["agent"]
    logs = TicketLog.objects.bulk_create(
        TicketLog(ticket=ticket, action="TRANSITION", operator=actor) for _ in range(14)
    )
    comments = TicketComment.objects.bulk_create(
        TicketComment(ticket=ticket, author=actor, body=f"回复 {index}", visibility=Visibility.PUBLIC)
        for index in range(14)
    )
    expected = []
    for index, (log, comment) in enumerate(zip(logs, comments, strict=True)):
        timestamp = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=index)
        log.created_time = comment.created_time = timestamp
        expected.extend(((timestamp, log.pk), (timestamp, comment.pk)))
    TicketLog.objects.bulk_update(logs, ["created_time"])
    TicketComment.objects.bulk_update(comments, ["created_time"])

    api = client_for(actor)
    resource = f"{TICKETS}/{ticket.pk}"
    detail = api.get(resource)
    assert detail.status_code == 200, detail.data
    timeline = detail.json()["data"]["timeline"]
    pages = []
    for page_number in (1, 2):
        response = api.get(f"{resource}/timeline", {"page": page_number, "size": 20})
        assert response.status_code == 200, response.data
        pages.append(response.json()["data"])

    assert timeline["total"] == pages[0]["total"] == pages[1]["total"] == len(expected)
    assert len(timeline["results"]) == 20
    assert timeline["results"] == pages[0]["results"]
    ids = [row["id"] for row in pages[0]["results"] + pages[1]["results"]]
    assert ids == [str(pk) for _, pk in sorted(expected, reverse=True)]


def test_dashboard_cache_is_scoped_to_viewer_and_invalidated_on_create(
    users, make_ticket, client_for, details, django_capture_on_commit_callbacks
):
    requester = client_for(users["requester"])
    agent = client_for(users["agent"])
    make_ticket(assignee=users["agent"])
    make_ticket(users["admin"], priority=Priority.P0, assignee=users["agent"])
    url = f"{TICKETS}/dashboard"

    def dashboard(api):
        response = api.get(url, {"status": Status.OPEN})
        assert response.status_code == 200, response.data
        return response.data["data"]

    initial_requester = dashboard(requester)
    initial_agent = dashboard(agent)
    assert initial_requester["status"] == {Status.OPEN: 1}
    assert initial_requester["priority"] == {Priority.P1: 1}
    assert initial_agent["status"] == {Status.OPEN: 2}
    assert initial_agent["priority"] == {Priority.P0: 1, Priority.P1: 1}
    with CaptureQueriesContext(connection) as captured:
        assert dashboard(agent) == initial_agent
        assert dashboard(requester) == initial_requester
    assert all(Ticket._meta.db_table not in query["sql"] for query in captured.captured_queries)

    with django_capture_on_commit_callbacks(execute=True):
        created = requester.post(TICKETS, details, format="json", HTTP_IDEMPOTENCY_KEY=str(uuid4()))
    assert created.status_code == 201, created.data

    refreshed_requester = dashboard(requester)
    refreshed_agent = dashboard(agent)
    assert refreshed_requester["status"] == {Status.OPEN: 2}
    assert refreshed_requester["priority"] == {Priority.P1: 2}
    assert refreshed_agent["status"] == {Status.OPEN: 3}
    assert refreshed_agent["priority"] == {Priority.P0: 1, Priority.P1: 2}


def test_export_task_replays_submitted_filter_with_current_ticket_scope(
    users, make_ticket, client_for, settings, django_capture_on_commit_callbacks
):
    settings.CELERY_TASK_ALWAYS_EAGER = False
    admin = users["admin"]
    visible = make_ticket(status=Status.CLOSED, title="本人处理的关闭工单", assignee=admin)
    other_department = DeptInfo.objects.create(code="export-other", name="其他支持部门")
    hidden = make_ticket(status=Status.CLOSED, department=other_department)
    make_ticket(status=Status.OPEN)
    api = client_for(admin)
    closed_rows = api.get(TICKETS, {"status": Status.CLOSED}).data["data"]["results"]
    assert {row["pk"] for row in closed_rows} == {str(visible.pk), str(hidden.pk)}

    with (
        patch.object(async_export_data_task, "apply_async") as dispatch,
        django_capture_on_commit_callbacks(execute=True),
    ):
        submitted = api.post(f"{TICKETS}/export-async", {"type": "csv", "status": Status.CLOSED}, format="json")
    assert submitted.status_code == 200, submitted.data
    record_id = submitted.data["data"]["record_id"]
    assert submitted.data["data"]["task_id"] == record_id
    record = ExportRecord.objects.get(pk=record_id)
    assert record.creator_id == admin.pk
    assert record.status == ExportRecord.Status.PENDING
    dispatch.assert_called_once()
    assert dispatch.call_args.kwargs["task_id"] == record_id
    assert dispatch.call_args.kwargs["args"][2] == {"type": "csv", "status": Status.CLOSED}

    # 保留导出及下载动作授权，只撤销可查看所有工单的业务角色。
    agent_role = users["agent"].roles.get()
    agent_role.menu.add(
        *admin.roles.get().menu.filter(
            name__in=("exportAsync:TicketFlowTickets", "exportData:TicketFlowTickets", "download:SystemExportRecord")
        )
    )
    admin.roles.set([agent_role])
    assert async_export_data_task.apply(**dispatch.call_args.kwargs, throw=True).get() == 1

    record.refresh_from_db()
    assert record.status == ExportRecord.Status.SUCCESS
    assert record.rows == 1
    url = f"/api/task/exports/{record_id}/download"
    download = api.get(url)
    assert download.status_code == 200
    contents = b"".join(download.streaming_content).decode("utf-8-sig")
    _, *rows = csv.reader(io.StringIO(contents))
    assert len(rows) == 1
    assert {visible.number, visible.title} <= set(rows[0])
    assert_error(client_for(users["requester"]).get(url), 403)


@pytest.mark.parametrize("assignment", ["current", "history", "unassigned"])
def test_export_task_replays_assignment_as_submitter(
    users, make_ticket, client_for, settings, django_capture_on_commit_callbacks, assignment
):
    settings.CELERY_TASK_ALWAYS_EAGER = False
    agent, admin = users["agent"], users["admin"]
    current = make_ticket(assignee=agent)
    history = make_ticket()
    waiting = make_ticket()
    make_ticket(status=Status.CLOSED)
    now = timezone.now()
    TicketAssignment.objects.create(ticket=history, assignee=agent, started_at=now, ended_at=now, end_reason="RETURNED")

    if assignment != "unassigned":
        agent.roles.get().menu.add(
            *admin.roles.get().menu.filter(
                name__in=(
                    "exportAsync:TicketFlowTickets",
                    "exportData:TicketFlowTickets",
                    "download:SystemExportRecord",
                )
            )
        )
    submitter = admin if assignment == "unassigned" else agent
    expected = {"current": [current], "history": [history], "unassigned": [history, waiting]}[assignment]
    api = client_for(submitter)
    params = {"type": "csv", "assignment": assignment}
    with (
        patch.object(async_export_data_task, "apply_async") as dispatch,
        django_capture_on_commit_callbacks(execute=True),
    ):
        response = api.post(f"{TICKETS}/export-async", params, format="json")
    assert response.status_code == 200, response.data
    record = ExportRecord.objects.get(pk=response.data["data"]["record_id"])
    assert dispatch.call_args.kwargs["args"][2:] == [params, submitter.pk]
    assert async_export_data_task.apply(**dispatch.call_args.kwargs, throw=True).get() == len(expected)
    record.refresh_from_db()
    assert record.status == ExportRecord.Status.SUCCESS
    assert record.rows == len(expected)
    download = api.get(f"/api/task/exports/{record.pk}/download")
    assert download.status_code == 200, download.data
    _, *rows = csv.reader(io.StringIO(b"".join(download.streaming_content).decode("utf-8-sig")))
    assert len(rows) == len(expected)
    numbers = {value for row in rows for value in row if value.startswith("TF-")}
    assert numbers == {ticket.number for ticket in expected}


def test_ai_context_requires_handling_scope_and_exposes_only_published_references(users, make_ticket, client_for):
    agent = users["agent"]
    api = client_for(agent)
    other_department = DeptInfo.objects.create(code="ai-other", name="其他支持部门")
    unhandled = make_ticket(agent, department=other_department)
    resource = f"{TICKETS}/{unhandled.pk}"
    assert api.get(resource).status_code == 200
    assert_error(api.get(f"{resource}/ai-context"), 403)

    ticket = make_ticket(title="Wireguard failure", assignee=agent)
    articles = {
        status: KnowledgeArticle.objects.create(
            title=f"Wireguard {status}",
            body_markdown=f"Wireguard {status} troubleshooting",
            category=ticket.category,
            status=status,
            creator=agent,
        )
        for status in ArticleStatus
    }
    resource = f"{TICKETS}/{ticket.pk}/ai-context"
    allowed = api.get(resource)
    assert allowed.status_code == 200, allowed.data
    data = allowed.data["data"]
    published = articles[ArticleStatus.PUBLISHED]
    assert data["ticket"]["description"] == ticket.description
    assert data["references"] == [
        {"article_id": str(published.pk), "title": published.title, "excerpt": published.body_markdown}
    ]


def test_ai_context_rejects_missing_required_field(users, make_ticket, client_for):
    agent = users["agent"]
    menu = Menu.objects.get(name="context:TicketFlowTickets")
    permissions = FieldPermission.objects.get(role=agent.roles.get(), menu=menu)
    permissions.field.remove(permissions.field.get(name="description", parent__name="tickets.ticket"))
    ticket = make_ticket(assignee=users["agent"])
    restricted = client_for(agent).get(f"{TICKETS}/{ticket.pk}/ai-context")
    assert_error(restricted, 403)
    assert "字段权限" in restricted.data["detail"]


def test_ticket_list_and_detail_queries_do_not_grow_with_rows(users, make_ticket, client_for):
    agent = users["agent"]
    ticket = make_ticket(assignee=agent)
    TicketLog.objects.create(ticket=ticket, action="CREATE", operator=users["requester"])
    TicketComment.objects.create(ticket=ticket, author=agent, body="首次回复", visibility=Visibility.PUBLIC)
    api = client_for(agent)
    resource = f"{TICKETS}/{ticket.pk}"

    def query_counts(total, timeline_size):
        with CaptureQueriesContext(connection) as list_queries:
            result = api.get(TICKETS, {"size": 20})
        assert result.status_code == 200, result.data
        rows = result.data["data"]["results"]
        assert result.data["data"]["total"] == len(rows) == total
        assert {row["assignee_name"] for row in rows} == {agent.username}
        assert {row["submitter_name"] for row in rows} == {users["requester"].username}
        assert {row["department_name"] for row in rows} == {agent.dept.name}

        with CaptureQueriesContext(connection) as detail_queries:
            result = api.get(resource)
        assert result.status_code == 200, result.data
        data = result.data["data"]
        assert data["assignee_name"] == agent.username
        timeline = data["timeline"]
        assert timeline["total"] == len(timeline["results"]) == timeline_size
        assert {row["actor"] for row in timeline["results"]} == {agent.username, users["requester"].username}
        return len(list_queries), len(detail_queries)

    # 预热公共权限缓存，查询预算只比较相同缓存条件下的资源读取。
    assert api.get(TICKETS).status_code == api.get(resource).status_code == 200
    small = query_counts(total=1, timeline_size=2)
    for _ in range(11):
        make_ticket(assignee=agent)
    TicketLog.objects.bulk_create(TicketLog(ticket=ticket, action="TRANSITION", operator=agent) for _ in range(8))
    TicketComment.objects.bulk_create(
        TicketComment(ticket=ticket, author=users["requester"], body="补充", visibility=Visibility.PUBLIC)
        for _ in range(8)
    )
    large = query_counts(total=12, timeline_size=18)
    assert small == large == (7, 13)


def test_create_rate_limit_returns_retry_after_without_creating_another_ticket(users, client_for, details):
    api = client_for(users["requester"])
    for _ in range(30):
        accepted = api.post(TICKETS, details, format="json", HTTP_IDEMPOTENCY_KEY=str(uuid4()))
        assert accepted.status_code == 201, accepted.data
    limited = api.post(TICKETS, details, format="json", HTTP_IDEMPOTENCY_KEY=str(uuid4()))
    assert_error(limited, 429)
    assert 0 < int(limited["Retry-After"]) <= WINDOW_SECONDS
    assert Ticket.objects.count() == 30


def test_create_fails_closed_when_rate_limit_redis_is_unavailable(users, client_for, details, monkeypatch):
    from django_redis import get_redis_connection
    from redis.exceptions import ConnectionError as RedisConnectionError

    redis = get_redis_connection()
    evaluate = redis.eval

    def fail_rate_limit(script, numkeys, key, *args):
        if f"{TICKET_CACHE_KEY_PREFIX}rate:" in key:
            raise RedisConnectionError("rate-limit Redis unavailable")
        return evaluate(script, numkeys, key, *args)

    monkeypatch.setattr(redis, "eval", fail_rate_limit)
    monkeypatch.setattr("tickets.cache.get_redis_connection", lambda: redis)
    api = client_for(users["requester"])
    unavailable = api.post(TICKETS, details, format="json", HTTP_IDEMPOTENCY_KEY=str(uuid4()))
    assert_error(unavailable, 503)
    assert not Ticket.objects.exists()
    assert not TicketCreateRequest.objects.exists()
