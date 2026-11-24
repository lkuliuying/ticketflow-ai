import json
import os
import re
from time import monotonic
from uuid import UUID, uuid4

import pytest

ANALYZE = "/ai/v1/tickets/analyze"
STREAM = "/ai/v1/tickets/suggest-reply/stream"
CHAT = "/ai/v1/assistant/chat/stream"
DRAFT = "/ai/v1/assistant/handoff-draft"
GATEWAY_MOCK = os.environ.get("TICKETFLOW_GATEWAY_MOCK") == "1"


def assert_ai_failure(response, status, error):
    assert response.status_code == status, response.text
    payload = response.json()
    assert set(payload) == {"code", "error", "detail"}
    assert payload["code"] == status and payload["error"] == error
    assert isinstance(payload["detail"], str) and payload["detail"]
    print(f"AI {status}: {payload}")


@pytest.mark.parametrize("credential", ["missing", "refresh", "invalid-signature"])
def test_analyze_rejects_invalid_access(gateway, agent, ticket, credential):
    token = None
    if credential == "refresh":
        token = agent.refresh
    elif credential == "invalid-signature":
        header, claims, signature = agent.access.split(".")
        changed = "B" if signature[0] == "A" else "A"
        token = f"{header}.{claims}.{changed}{signature[1:]}"
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    assert_ai_failure(gateway.post(ANALYZE, headers=headers, json={"ticket_id": ticket["pk"]}), 401, "UNAUTHORIZED")


def test_analyze_rejects_ticket_requester(gateway, requester, ticket):
    response = gateway.post(ANALYZE, headers=requester.headers, json={"ticket_id": ticket["pk"]})
    assert_ai_failure(response, 403, "FORBIDDEN")


def test_ai_access_follows_reassignment(gateway, login, agent, other_agent, transition_ticket):
    ticket = transition_ticket
    payload = {"ticket_id": ticket["pk"]}
    assert ticket["assignee_name"] == agent.username
    before = gateway.post(ANALYZE, headers=agent.headers, json=payload)
    assert before.status_code == 200, before.text

    admin = login("tf_admin")
    path = f"/api/tickets/{ticket['pk']}"
    candidates = gateway.get(f"{path}/assignees", params={"q": other_agent.username}, headers=admin.headers)
    assert candidates.status_code == 200, candidates.text
    assignee = next(row for row in candidates.json()["data"] if row["username"] == other_agent.username)
    assigned = gateway.post(
        f"{path}/assign", headers=admin.headers, json={"assignee_id": assignee["pk"], "version": ticket["version"]}
    )
    assert assigned.status_code == 200, assigned.text
    assert_ai_failure(gateway.post(ANALYZE, headers=agent.headers, json=payload), 403, "FORBIDDEN")
    assert_ai_failure(gateway.post(STREAM, headers=agent.headers, json=payload), 403, "FORBIDDEN")
    current = gateway.post(ANALYZE, headers=other_agent.headers, json=payload)
    assert current.status_code == 200, current.text


def test_logout_revokes_ai_access(gateway, login, ticket):
    session = login("tf_agent")
    payload = {"ticket_id": ticket["pk"]}
    before = gateway.post(ANALYZE, headers=session.headers, json=payload)
    assert before.status_code == 200, before.text
    analysis = before.json()
    assert analysis["ticket_id"] == ticket["pk"]
    assert analysis["suggested_priority"] in {"P0", "P1", "P2", "P3"}
    print(f"AI analysis: HTTP 200, {analysis}")
    logout = gateway.post("/api/identity/logout", headers=session.headers, json={"refresh": session.refresh})
    assert logout.status_code == 200, logout.text
    assert logout.json()["code"] == 1000 and isinstance(logout.json()["detail"], str)
    assert_ai_failure(gateway.post(ANALYZE, headers=session.headers, json=payload), 401, "UNAUTHORIZED")


def read_stream(gateway, path, headers, body):
    headers = {**headers, "Accept-Encoding": "gzip"}
    events = []
    frame = {}
    start = monotonic()
    with gateway.stream("POST", path, headers=headers, json=body) as response:
        assert response.status_code == 200, response.read().decode()
        assert response.headers["content-type"].split(";", 1)[0].strip().lower() == "text/event-stream"
        assert "gzip" not in response.headers.get("content-encoding", "").lower()
        for line in response.iter_lines():
            if line:
                key, value = line.split(":", 1)
                assert key in ("event", "data") and key not in frame
                frame[key] = value.lstrip()
            elif frame:
                events.append((frame["event"], json.loads(frame["data"]), monotonic() - start))
                frame.clear()

    assert not frame
    return events


def test_reply_stream_arrives_incrementally(gateway, other_agent):
    title = "园区 VPN 无法连接"
    response = gateway.get("/api/tickets", params={"q": title}, headers=other_agent.headers)
    assert response.status_code == 200, response.text
    tickets = [ticket for ticket in response.json()["data"]["results"] if ticket["title"] == title]
    assert tickets, "交付栈缺少可触发知识引用的 VPN 演示工单"
    ticket = tickets[0]
    events = read_stream(gateway, STREAM, other_agent.headers, {"ticket_id": ticket["pk"]})
    sequence = " ".join(name for name, _, _ in events)
    assert re.fullmatch(r"meta (?:ping |delta )*delta (?:ping |delta )*done", sequence), sequence
    meta = events[0][1]
    assert meta["ticket_id"] == ticket["pk"]
    assert isinstance(meta["ticket_version"], int) and isinstance(meta["references"], list)
    for reference in meta["references"]:
        assert isinstance(reference, dict) and set(reference) == {"article_id", "title"}
        assert str(UUID(reference["article_id"])) == reference["article_id"]
        assert isinstance(reference["title"], str) and reference["title"]
    assert any(reference["title"] == "VPN 连接失败排查指南" for reference in meta["references"])
    print(f"SSE meta: {json.dumps(meta, ensure_ascii=False)}")
    deltas = [(data, elapsed) for name, data, elapsed in events if name == "delta"]
    assert all(isinstance(data["text"], str) and data["text"] for data, _ in deltas)
    assert isinstance(events[-1][1]["finish_reason"], str)
    first_delta, done = deltas[0][1], events[-1][2]
    print(f"SSE {sequence}: first delta={first_delta:.3f}s, done={done:.3f}s, Content-Encoding has no gzip")
    if GATEWAY_MOCK:
        assert first_delta < done / 2


@pytest.fixture
def assistant_session(gateway, requester):
    response = gateway.post("/api/assistant/sessions", headers=requester.headers, json={})
    assert response.status_code == 201, response.text
    session_id = response.json()["data"]["pk"]
    yield session_id
    response = gateway.delete(f"/api/assistant/sessions/{session_id}", headers=requester.headers)
    assert response.status_code == 204, response.text


def test_assistant_stream_persists_answer_through_gateway(gateway, requester, assistant_session):
    body = {"session_id": assistant_session, "message": "VPN"}
    events = read_stream(gateway, CHAT, requester.headers, body)
    names = [event for event, _, _ in events]
    assert names and names[0] == "meta" and names[-1] == "done", names
    assert "delta" in names[1:-1] and set(names[1:-1]) <= {"delta", "ping"}, names
    meta, done = events[0][1], events[-1][1]
    assert set(meta) == {"session_id", "user_message_id", "references"}
    assert meta["session_id"] == assistant_session
    assert str(UUID(meta["user_message_id"])) == meta["user_message_id"]
    assert isinstance(meta["references"], list)
    for ref in meta["references"]:
        assert isinstance(ref, dict) and set(ref) == {"article_id", "title"}
        assert str(UUID(ref["article_id"])) == ref["article_id"]
        assert isinstance(ref["title"], str) and ref["title"]
    assert any(ref["title"] == "VPN 连接失败排查指南" for ref in meta["references"])
    assert set(done) == {"finish_reason", "assistant_message_id"}
    assert done["finish_reason"] == "stop"
    assert str(UUID(done["assistant_message_id"])) == done["assistant_message_id"]
    response = gateway.get(f"/api/assistant/sessions/{assistant_session}/messages", headers=requester.headers)
    assert response.status_code == 200, response.text
    messages = {message["pk"]: message for message in response.json()["data"]["results"]}
    assert messages[meta["user_message_id"]]["content"] == body["message"]
    answer = messages[done["assistant_message_id"]]
    delta_frames = [data for event, data, _ in events if event == "delta"]
    assert all(set(frame) == {"text"} and isinstance(frame["text"], str) and frame["text"] for frame in delta_frames)
    deltas = [frame["text"] for frame in delta_frames]
    assert answer["content"] == "".join(deltas)
    assert answer["user_message_id"] == meta["user_message_id"]
    assert answer["status"] == "complete" and answer["references"] == meta["references"]
    first_delta = next(elapsed for event, _, elapsed in events if event == "delta")
    print(
        f"Assistant SSE {' '.join(names)}: first delta={first_delta:.3f}s, done={events[-1][2]:.3f}s, stored=complete"
    )
    if GATEWAY_MOCK:
        assert first_delta < events[-1][2] / 2
    for event, data in [("meta", meta), ("delta", {"text": deltas[0]}), ("done", done)]:
        print(f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n")


def test_assistant_handoff_draft_through_gateway(gateway, requester, assistant_session):
    message = "VPN 客户端连接时超时"
    chat = read_stream(gateway, CHAT, requester.headers, {"session_id": assistant_session, "message": message})
    assert chat[-1][0] == "done"
    response = gateway.post(DRAFT, headers=requester.headers, json={"session_id": assistant_session})
    assert response.status_code == 200, response.text
    draft = response.json()
    assert set(draft) == {"title", "description", "category"}
    assert draft["category"] in {"ACCOUNT", "ACCESS", "NETWORK", "SERVICE", "OTHER"}
    assert isinstance(draft["title"], str) and draft["title"].strip() and len(draft["title"]) <= 200
    assert isinstance(draft["description"], str) and draft["description"].strip() and len(draft["description"]) <= 20000
    print(f"Assistant handoff draft HTTP 200: {json.dumps(draft, ensure_ascii=False)}")
    if GATEWAY_MOCK:
        assert draft == {"title": message, "description": message, "category": "OTHER"}


def test_assistant_rejects_new_question_after_handoff_through_gateway(gateway, requester, assistant_session):
    message = "VPN 客户端连接时超时"
    events = read_stream(gateway, CHAT, requester.headers, {"session_id": assistant_session, "message": message})
    assert events[-1][0] == "done"

    handoff = gateway.post(
        "/api/tickets",
        headers={**requester.headers, "Idempotency-Key": str(uuid4())},
        json={
            "title": message,
            "description": message,
            "category": "NETWORK",
            "priority": "P2",
            "assistant_session_id": assistant_session,
        },
    )
    assert handoff.status_code == 201, handoff.text
    ticket_id = handoff.json()["data"]["pk"]
    ticket = gateway.get(f"/api/tickets/{ticket_id}", headers=requester.headers)
    assert ticket.status_code == 200, ticket.text
    assert ticket.json()["data"]["assistant_session_id"] == assistant_session

    response = gateway.post(
        CHAT, headers=requester.headers, json={"session_id": assistant_session, "message": "还有其他排查方法吗？"}
    )
    assert_ai_failure(response, 409, "CONFLICT")
    assert response.headers["content-type"].split(";", 1)[0] == "application/json"

    transcript = gateway.get(f"/api/assistant/sessions/{assistant_session}/messages", headers=requester.headers)
    assert transcript.status_code == 200, transcript.text
    data = transcript.json()["data"]
    assert data["total"] == 2
    assert {item["pk"] for item in data["results"]} == {
        events[0][1]["user_message_id"],
        events[-1][1]["assistant_message_id"],
    }
