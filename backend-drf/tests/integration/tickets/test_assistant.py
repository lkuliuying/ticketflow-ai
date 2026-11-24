from datetime import timedelta
from uuid import uuid4

import pytest
from django.core.cache import cache
from django.utils import timezone
from django_redis import get_redis_connection
from redis.exceptions import ConnectionError
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from common.core.permission import IsAuthenticated
from identity.models import UserInfo
from knowledge.models import ArticleStatus, KnowledgeArticle
from tests.integration.tickets.test_ticket_api import assert_error, authenticated
from tests.integration.tickets.test_viewer_contract import validate
from tickets.cache import TICKET_CACHE_KEY_PREFIX
from tickets.models import (
    AssistantFeedback,
    AssistantMessage,
    AssistantSession,
    Category,
    Status,
    Ticket,
    TicketAssignment,
)

pytestmark = pytest.mark.django_db
SESSIONS = "/api/assistant/sessions"
INTERNAL = "/api/assistant/internal/sessions"
FEEDBACK = "/api/assistant/feedback"


def data(response, status=200):
    assert response.status_code == status, response.content
    payload = response.json()
    assert payload["code"] == 1000
    return payload["data"]


def new_session(api, title=None):
    session = data(api.post(SESSIONS, {} if title is None else {"title": title}, format="json"), 201)
    validate(session, "assistantSession")
    return session


def ask(api, session_id, message):
    result = data(api.post(f"{INTERNAL}/{session_id}/question", {"message": message}, format="json"), 201)
    validate(result, "assistantQuestionContext")
    return result


def answer(api, session_id, question_id, **overrides):
    payload = {"user_message_id": question_id, "content": "连接 VPN 后重试", "status": "complete", "references": []}
    result = data(api.post(f"{INTERNAL}/{session_id}/answer", payload | overrides, format="json"))
    validate(result, "assistantAnswerResult")
    return result["assistant_message_id"]


@pytest.fixture
def employee(users, client_for):
    return client_for(users["requester"])


@pytest.fixture
def teammate(users):
    user = UserInfo.objects.create_user(username="other-employee")
    user.roles.set(users["requester"].roles.all())
    return user


def test_employee_session_scope_rename_and_soft_delete(users, employee, teammate, client_for, settings):
    settings.PERMISSION_FIELD_ENABLED = True
    session = new_session(employee)
    session_id = session["pk"]
    path = f"{SESSIONS}/{session_id}"
    assert session["title"] == "新对话"
    assert session["ticket_id"] is None

    foreign = client_for(teammate)
    assert data(foreign.get(SESSIONS)) == {"total": 0, "results": []}
    assert_error(foreign.patch(path, {"title": "越权修改"}, format="json"), 404)
    assert_error(foreign.delete(path), 404)
    assert_error(foreign.get(f"{path}/messages"), 404)
    renamed = data(employee.patch(path, {"title": " 网络故障 "}, format="json"))
    assert renamed["title"] == "网络故障"
    assert_error(employee.patch(path, {}, format="json"), 400)
    assert_error(employee.patch(path, {"title": ""}, format="json"), 400)
    assert_error(employee.post(SESSIONS, {"title": ""}, format="json"), 400)
    assert_error(employee.post(SESSIONS, {"title": "a" * 201}, format="json"), 400)
    assert_error(employee.post(f"{INTERNAL}/{session_id}/question", {"message": ""}, format="json"), 400)
    assert data(employee.get(SESSIONS, {"size": 1})) == {"total": 1, "results": [renamed]}
    user_message_id = ask(employee, session_id, "VPN 无法连接")["user_message_id"]

    response = employee.delete(path)
    assert response.status_code == 204 and not response.content
    assert data(employee.get(SESSIONS)) == {"total": 0, "results": []}
    assert_error(employee.get(f"{path}/messages"), 404)
    assert_error(employee.get(f"{INTERNAL}/{session_id}/context"), 404)
    assert AssistantSession.all_objects.get(pk=session_id).deleted_at is not None
    assert AssistantMessage.objects.filter(pk=user_message_id).exists()


def test_role_guards_apply_even_after_extra_menu_grants(users, employee, client_for, monkeypatch):
    session_id = new_session(employee)["pk"]
    monkeypatch.setattr(IsAuthenticated, "has_permission", lambda *args: True)
    for user in (users["admin"], users["agent"], UserInfo.objects.create(username="roleless")):
        api = client_for(user)
        assert_error(api.get(SESSIONS), 403)
        assert_error(api.post(SESSIONS, {}, format="json"), 403)
        assert_error(api.get(f"{INTERNAL}/{session_id}/context"), 403)
    assert_error(employee.get(f"{FEEDBACK}/summary"), 403)
    assert_error(client_for(users["agent"]).get(f"{FEEDBACK}/downvotes"), 403)
    assert data(client_for(users["admin"]).get(f"{FEEDBACK}/summary"))["sessions"] == 1


def test_internal_context_uses_bearer_scope_published_articles_and_bounded_history(users, teammate):
    employee = authenticated(users["requester"])
    session_id = new_session(employee)["pk"]
    path = f"{INTERNAL}/{session_id}"
    assert_error(APIClient().post(f"{path}/question", {"message": "VPN"}, format="json"), 401)
    refresh = RefreshToken.for_user(users["requester"])
    assert_error(APIClient(HTTP_AUTHORIZATION=f"Bearer {refresh}").get(f"{path}/context"), 401)
    assert_error(authenticated(teammate).post(f"{path}/question", {"message": "VPN"}, format="json"), 404)
    assert_error(authenticated(users["agent"]).get(f"{path}/context"), 403)
    assert_error(authenticated(users["admin"]).get(f"{path}/context"), 403)

    articles = [
        KnowledgeArticle.objects.create(
            title=f"VPN {status}", body_markdown="VPN 设置 " + "步骤" * 500, category=Category.NETWORK, status=status
        )
        for status in ArticleStatus.values
    ]
    context = ask(employee, session_id, "VPN")
    assert context["history"] == []
    assert context["categories"] == Category.values
    (reference,) = context["references"]
    published = next(article for article in articles if article.status == ArticleStatus.PUBLISHED)
    assert reference["article_id"] == str(published.pk)
    assert len(reference["excerpt"]) == 800
    answer(employee, session_id, context["user_message_id"], content="A" * 12000)
    following = ask(employee, session_id, "error")
    assert [(row["role"], len(row["content"])) for row in following["history"]] == [("user", 3), ("assistant", 7997)]
    assert following["references"] == []
    reopened = data(employee.get(f"{path}/context"))
    validate(reopened, "assistantContext")
    assert reopened["history"][-1] == {"role": "user", "content": "error"}
    assert sum(len(row["content"]) for row in reopened["history"]) == 8000


def test_internal_context_and_question_cap_history_and_references(employee):
    session_id = new_session(employee)["pk"]
    path = f"{INTERNAL}/{session_id}"
    for turn in range(11):
        question = ask(employee, session_id, f"问题 {turn}")
        answer(employee, session_id, question["user_message_id"], content=f"回答 {turn}")

    KnowledgeArticle.objects.bulk_create(
        KnowledgeArticle(
            title=f"VPN 设置 {index}",
            body_markdown="VPN 连接步骤",
            category=Category.NETWORK,
            status=ArticleStatus.PUBLISHED,
        )
        for index in range(7)
    )
    expected_history = [
        {"role": role, "content": f"{label} {turn}"}
        for turn in range(1, 11)
        for role, label in (("user", "问题"), ("assistant", "回答"))
    ]

    context = data(employee.get(f"{path}/context"))
    validate(context, "assistantContext")
    assert context["history"] == expected_history
    question = ask(employee, session_id, "VPN 连不上")
    assert question["history"] == expected_history
    assert len({ref["article_id"] for ref in question["references"]}) == 5


def test_internal_writeback_replay_status_and_message_pagination(employee, teammate, client_for):
    session_id = new_session(employee)["pk"]
    second_id = new_session(employee)["pk"]
    question_id = ask(employee, session_id, "VPN")["user_message_id"]
    path = f"{INTERNAL}/{session_id}/answer"
    payload = {"user_message_id": question_id, "content": " 部分内容 ", "status": "interrupted", "references": []}
    assert_error(client_for(teammate).post(path, payload, format="json"), 404)
    assert_error(employee.post(f"{INTERNAL}/{second_id}/answer", payload, format="json"), 404)
    assert_error(employee.post(path, payload | {"status": "complete", "content": " "}, format="json"), 400)
    reference = {"article_id": str(uuid4()), "title": "VPN 设置"}
    first = answer(employee, session_id, question_id, **(payload | {"references": [reference]}))
    assert answer(employee, session_id, question_id) == first
    failed_question = ask(employee, session_id, "重试")["user_message_id"]
    failed_answer = answer(employee, session_id, failed_question, status="failed", content="")
    assert_error(employee.post(path, payload | {"user_message_id": first}, format="json"), 404)

    messages_path = f"{SESSIONS}/{session_id}/messages"
    question_page = data(employee.get(messages_path, {"page": 1, "size": 1}))
    answer_page = data(employee.get(messages_path, {"page": 2, "size": 1}))
    assert question_page["total"] == answer_page["total"] == 4
    assert question_page["results"][0]["pk"] == question_id
    (row,) = answer_page["results"]
    validate(row, "assistantMessage")
    assert (row["pk"], row["content"], row["status"]) == (first, " 部分内容 ", "interrupted")
    assert row["user_message_id"] == question_id and row["references"] == [reference] and row["feedback"] is None
    assert data(employee.get(messages_path))["results"][-1]["pk"] == failed_answer
    assert [row["role"] for row in data(employee.get(f"{INTERNAL}/{session_id}/context"))["history"]] == [
        "user",
        "user",
    ]


def test_feedback_revote_admin_visibility_and_dates(users, employee, teammate, client_for, make_ticket):
    session_id = new_session(employee, "网络排障")["pk"]
    question_id = ask(employee, session_id, "VPN 连不上")["user_message_id"]
    answer_id = answer(employee, session_id, question_id)
    resource = f"{SESSIONS}/{session_id}/messages"
    feedback_path = f"{resource}/{answer_id}/feedback"
    vote = {"vote": "down", "reason": "UNRESOLVED", "comment": "仍然无法连接"}
    assert_error(client_for(teammate).put(feedback_path, vote, format="json"), 404)
    assert_error(employee.put(f"{resource}/{question_id}/feedback", vote, format="json"), 404)
    assert_error(employee.put(feedback_path, vote | {"comment": "a" * 301}, format="json"), 400)
    down = data(employee.put(feedback_path, vote, format="json"))
    validate(down, "assistantFeedback")
    assert down | vote == down
    assert data(employee.get(resource))["results"][-1]["feedback"] == down

    admin = client_for(users["admin"])
    (downvote,) = data(admin.get(f"{FEEDBACK}/downvotes"))["results"]
    validate(downvote, "assistantDownvote")
    assert downvote["session"]["ticket_number"] is None
    assert downvote["session"]["username"] == users["requester"].username
    assert downvote["question"]["pk"] == question_id
    assert downvote["answer"]["pk"] == answer_id and downvote["answer"]["feedback"] == down

    up = data(employee.put(feedback_path, {"vote": "up"}, format="json"))
    assert up["reason"] is None and up["comment"] == "" and up["created_time"] == down["created_time"]
    assert AssistantFeedback.objects.count() == 1
    assert data(admin.get(f"{FEEDBACK}/downvotes")) == {"total": 0, "results": []}
    ticket = make_ticket()
    AssistantSession.objects.filter(pk=session_id).update(ticket=ticket)
    assert employee.delete(f"{SESSIONS}/{session_id}").status_code == 204
    (handoff,) = data(admin.get(f"{FEEDBACK}/handoffs"))["results"]
    validate(handoff, "assistantHandoffSession")
    assert handoff["pk"] == session_id and handoff["ticket_number"] == ticket.number
    metrics = data(admin.get(f"{FEEDBACK}/summary"))
    validate(metrics, "assistantStats")
    assert metrics == {"sessions": 1, "questions": 1, "up": 1, "down": 0, "handoffs": 1}
    moment = up["updated_time"]
    params = {"created_from": moment, "created_to": moment}
    assert data(admin.get(f"{FEEDBACK}/summary", params)) == dict.fromkeys(metrics, 0) | {"up": 1}
    assert data(admin.get(f"{FEEDBACK}/handoffs", params)) == {"total": 0, "results": []}
    future = (timezone.now() + timedelta(days=1)).isoformat()
    assert_error(admin.get(f"{FEEDBACK}/summary", {"created_from": future, "created_to": moment}), 400)
    assert_error(admin.get(f"{FEEDBACK}/downvotes", {"created_to": "invalid"}), 400)


def test_handoff_create_replay_scope_and_retained_transcript(users, employee, teammate, client_for, details, settings):
    settings.PERMISSION_FIELD_ENABLED = True
    other_agent = UserInfo.objects.create_user(username="former-technician")
    other_agent.roles.set(users["agent"].roles.all())
    session_id = new_session(employee)["pk"]
    question_id = ask(employee, session_id, "VPN")["user_message_id"]
    answer_id = answer(employee, session_id, question_id)
    feedback_path = f"{SESSIONS}/{session_id}/messages/{answer_id}/feedback"
    data(employee.put(feedback_path, {"vote": "down", "comment": "助手补充反馈"}, format="json"))
    payload = {**details, "assistant_session_id": session_id}
    headers = {"HTTP_IDEMPOTENCY_KEY": str(uuid4())}
    assert_error(client_for(teammate).post("/api/tickets", payload, format="json", **headers), 404)
    assert_error(client_for(users["agent"]).post("/api/tickets", payload, format="json", **headers), 403)
    assert not Ticket.objects.exists()
    ticket = data(employee.post("/api/tickets", payload, format="json", **headers), 201)
    path = f"/api/tickets/{ticket['pk']}"
    assert data(employee.post("/api/tickets", payload, format="json", **headers)) == ticket
    assert_error(employee.post("/api/tickets", details, format="json", **headers), 409)
    assert_error(employee.post("/api/tickets", payload, format="json", HTTP_IDEMPOTENCY_KEY=str(uuid4())), 409)
    assert employee.delete(f"{SESSIONS}/{session_id}").status_code == 204
    assert data(employee.post("/api/tickets", payload, format="json", **headers)) == ticket
    assert Ticket.objects.count() == 1

    stored = Ticket.objects.get()
    stored.assignments.create(
        assignee=other_agent,
        started_at=stored.created_time,
        ended_at=timezone.now(),
        end_reason=TicketAssignment.EndReason.REASSIGNED,
    )
    assert stored.assignee_id == users["agent"].pk
    for user in users.values():
        api = client_for(user)
        detail = data(api.get(path))
        validate(detail, "ticketDetailAssistant")
        assert detail["assistant_session_id"] == session_id
        transcript = data(api.get(f"{path}/assistant-session"))
        assert transcript["session"]["ticket_id"] == ticket["pk"]
        assert transcript["messages"]["total"] == 2
        question, reply = transcript["messages"]["results"]
        assert question["pk"] == question_id and reply["pk"] == answer_id
        validate(reply, "assistantTranscriptMessage")
        assert "feedback" not in reply
    history = client_for(other_agent)
    assert data(history.get(path))["assistant_session_id"] is None
    assert_error(history.get(f"{path}/assistant-session"), 403)
    assert_error(client_for(teammate).get(f"{path}/assistant-session"), 404)


def test_handed_off_session_rejects_new_question_but_accepts_pending_answer(employee, details):
    session_id = new_session(employee)["pk"]
    question_id = ask(employee, session_id, "VPN 连接超时")["user_message_id"]
    data(
        employee.post(
            "/api/tickets",
            {**details, "assistant_session_id": session_id},
            format="json",
            HTTP_IDEMPOTENCY_KEY=str(uuid4()),
        ),
        201,
    )

    path = f"{INTERNAL}/{session_id}"
    response = employee.post(f"{path}/question", {"message": "补充提问"}, format="json")
    assert_error(response, 409)
    assert response.json()["detail"] == "会话已转人工，请新建对话"
    assert list(AssistantMessage.objects.filter(session_id=session_id).values_list("role", flat=True)) == ["user"]

    answer_id = answer(employee, session_id, question_id)
    assert answer(employee, session_id, question_id, content="重复写回") == answer_id
    assert AssistantMessage.objects.get(pk=answer_id).content == "连接 VPN 后重试"


def test_assistant_rate_limits_and_fails_closed(employee, users, monkeypatch):
    session_id = new_session(employee)["pk"]
    path = f"{INTERNAL}/{session_id}"
    key = cache.make_key(f"{TICKET_CACHE_KEY_PREFIX}rate:assistant-context:{users['requester'].pk}")
    redis = get_redis_connection()
    seconds, microseconds = redis.time()
    clock = seconds * 1000 + microseconds // 1000
    redis.zadd(key, {str(index): clock for index in range(60)})
    redis.expire(key, 60)
    response = employee.post(f"{path}/question", {"message": "VPN"}, format="json")
    assert_error(response, 429)
    assert int(response["Retry-After"]) > 0
    assert not AssistantMessage.objects.exists()

    def unavailable():
        raise ConnectionError("unavailable")

    monkeypatch.setattr("tickets.cache.get_redis_connection", unavailable)
    assert_error(employee.get(f"{path}/context"), 503)


@pytest.mark.parametrize("role", ["requester", "agent"])
def test_ticket_create_treats_null_assistant_session_as_absent(users, client_for, details, settings, role):
    settings.PERMISSION_FIELD_ENABLED = True
    api = client_for(users[role])
    headers = {"HTTP_IDEMPOTENCY_KEY": str(uuid4())}
    payload = {**details, "assistant_session_id": None}
    validate(payload, "ticketCreate")
    ticket = data(api.post("/api/tickets", payload, format="json", **headers), 201)
    assert data(api.post("/api/tickets", details, format="json", **headers)) == ticket
    assert data(api.get(f"/api/tickets/{ticket['pk']}"))["assistant_session_id"] is None


def test_ticket_create_rejects_deleted_assistant_session(employee, details):
    session_id = new_session(employee)["pk"]
    assert employee.delete(f"{SESSIONS}/{session_id}").status_code == 204
    assert_error(
        employee.post(
            "/api/tickets",
            {**details, "assistant_session_id": session_id},
            format="json",
            HTTP_IDEMPOTENCY_KEY=str(uuid4()),
        ),
        404,
    )
    assert not Ticket.objects.exists()


def test_ticket_without_assistant_session_returns_not_found(employee, make_ticket):
    ticket = make_ticket()
    assert_error(employee.get(f"/api/tickets/{ticket.pk}/assistant-session"), 404)


def test_closed_ticket_retains_assistant_transcript_for_submitter_assignee_and_admin(
    employee, users, client_for, details, settings
):
    settings.PERMISSION_FIELD_ENABLED = True
    session_id = new_session(employee)["pk"]
    question_id = ask(employee, session_id, "VPN")["user_message_id"]
    ticket = data(
        employee.post(
            "/api/tickets",
            {**details, "assistant_session_id": session_id},
            format="json",
            HTTP_IDEMPOTENCY_KEY=str(uuid4()),
        ),
        201,
    )
    path = f"/api/tickets/{ticket['pk']}"
    assignee = client_for(users["agent"])
    for api, target in ((assignee, Status.IN_PROGRESS), (assignee, Status.PENDING_VERIFY), (employee, Status.CLOSED)):
        ticket = data(
            api.post(f"{path}/transition", {"version": ticket["version"], "target_status": target}, format="json")
        )
    assert ticket["status"] == Status.CLOSED
    assert Ticket.objects.get(pk=ticket["pk"]).assignee_id == users["agent"].pk
    for api in (employee, assignee, client_for(users["admin"])):
        assert data(api.get(path))["assistant_session_id"] == session_id
        transcript = data(api.get(f"{path}/assistant-session"))
        assert transcript["session"]["pk"] == session_id
        assert [message["pk"] for message in transcript["messages"]["results"]] == [question_id]
