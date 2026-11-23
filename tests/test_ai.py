import json
import re
from time import monotonic
from uuid import UUID

import pytest

ANALYZE = "/ai/v1/tickets/analyze"
STREAM = "/ai/v1/tickets/suggest-reply/stream"


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


def test_reply_stream_arrives_incrementally(gateway, other_agent):
    title = "园区 VPN 无法连接"
    response = gateway.get("/api/tickets", params={"q": title}, headers=other_agent.headers)
    assert response.status_code == 200, response.text
    tickets = [ticket for ticket in response.json()["data"]["results"] if ticket["title"] == title]
    assert tickets, "交付栈缺少可触发知识引用的 VPN 演示工单"
    ticket = tickets[0]

    headers = {**other_agent.headers, "Accept-Encoding": "gzip"}
    events = []
    frame = {}
    start = monotonic()
    with gateway.stream("POST", STREAM, headers=headers, json={"ticket_id": ticket["pk"]}) as response:
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
    sequence = " ".join(name for name, _, _ in events)
    assert re.fullmatch(r"meta (?:ping )*(?:delta )+done", sequence), sequence
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
    assert first_delta < done / 2
