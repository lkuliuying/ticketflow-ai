from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from websockets.sync.client import connect


def test_ticket_list_envelope(gateway, agent, ticket):
    response = gateway.get("/api/tickets", params={"q": ticket["title"], "size": 5}, headers=agent.headers)
    assert response.status_code == 200, response.text
    envelope = response.json()
    assert envelope["code"] == 1000
    assert isinstance(envelope["detail"], str)
    page = envelope["data"]
    assert page["total"] == len(page["results"]) == 1
    summary = page["results"][0]
    assert summary["pk"] == ticket["pk"]
    assert isinstance(summary["version"], int) and isinstance(summary["sla_state"], str)
    print(f"Ticket list: HTTP 200, code={envelope['code']}, total={page['total']}, status={summary['status']}")


def assert_failure(response, status):
    assert response.status_code == status, response.text
    payload = response.json()
    assert isinstance(payload["code"], int) and payload["code"] != 1000
    assert isinstance(payload["detail"], str) and payload["detail"]
    print(f"{response.request.method} {response.request.url.path}: HTTP {status}, {payload}")


def test_ticket_access_control(gateway, requester, other_agent, ticket):
    assert_failure(gateway.get("/api/tickets"), 401)
    path = f"/api/tickets/{ticket['pk']}"
    visible = gateway.get(path, headers=requester.headers)
    assert visible.status_code == 200 and visible.json()["data"]["pk"] == ticket["pk"]
    forbidden = gateway.post(
        f"{path}/assign", headers=requester.headers, json={"assignee_id": None, "version": ticket["version"]}
    )
    assert_failure(forbidden, 403)
    assert_failure(gateway.get(path, headers=other_agent.headers), 404)


def test_concurrent_ticket_transition(gateway, agent, transition_ticket):
    path = f"/api/tickets/{transition_ticket['pk']}"
    payload = {"target_status": "IN_PROGRESS", "version": transition_ticket["version"]}
    start = Barrier(2, timeout=10)

    def transition():
        start.wait()
        return gateway.post(f"{path}/transition", headers=agent.headers, json=payload)

    with ThreadPoolExecutor(max_workers=2) as workers:
        pending = [workers.submit(transition) for _ in range(2)]
        success, conflict = sorted((request.result() for request in pending), key=lambda response: response.status_code)

    assert success.status_code == 200, success.text
    assert_failure(conflict, 409)
    envelope = success.json()
    assert envelope["code"] == 1000 and isinstance(envelope["detail"], str)
    assert envelope["data"]["status"] == "IN_PROGRESS"
    assert envelope["data"]["version"] == transition_ticket["version"] + 1
    stored = gateway.get(path, headers=agent.headers)
    assert stored.status_code == 200, stored.text
    assert stored.json()["data"]["version"] == envelope["data"]["version"]
    print(f"Concurrent transition: HTTP 200 and 409, committed version={envelope['data']['version']}")


def test_gateway_hides_ai_context(gateway, agent, ticket):
    response = gateway.get(f"/api/tickets/{ticket['pk']}/ai-context", headers=agent.headers)
    assert response.status_code == 404, response.text
    assert response.json() == {"detail": "Not Found"}
    print(f"Private context: HTTP 404, {response.json()}")


@pytest.mark.parametrize("method, action", [("POST", "question"), ("POST", "answer"), ("GET", "context")])
@pytest.mark.parametrize("suffix", ["", "/"])
def test_gateway_hides_assistant_internal_routes(gateway, method, action, suffix):
    session_id = "d5f24717-5e7d-4276-b472-888ccadb134d"
    response = gateway.request(
        method,
        f"/api/assistant/internal/sessions/{session_id}/{action}{suffix}",
        headers={"Authorization": "Bearer gateway-acceptance-probe"},
    )
    assert response.status_code == 404, response.text
    assert response.json() == {"detail": "Not Found"}


def test_gateway_proxies_employee_assistant_sessions(gateway, requester, agent):
    path = "/api/assistant/sessions"
    assert_failure(gateway.get(path), 401)
    assert_failure(gateway.get(path, headers=agent.headers), 403)
    response = gateway.post(path, headers=requester.headers, json={"title": "Gateway assistant acceptance"})
    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["code"] == 1000 and payload["data"]["ticket_id"] is None
    session_path = f"{path}/{payload['data']['pk']}"
    messages = gateway.get(f"{session_path}/messages", headers=requester.headers)
    assert messages.status_code == 200, messages.text
    assert messages.json()["data"] == {"total": 0, "results": []}
    assert gateway.delete(session_path, headers=requester.headers).status_code == 204
    assert_failure(gateway.get(f"{session_path}/messages", headers=requester.headers), 404)


@pytest.mark.parametrize("path", ["/api-docs", "/api-docs/", "/api-docs/login/", "/api-docs/schema/"])
def test_gateway_hides_api_docs(gateway, path):
    response = gateway.get(path)
    assert response.status_code == 404, response.text
    print(f"GET {path}: HTTP {response.status_code}")


def test_spa_fallback_and_security_headers(gateway):
    homepage = gateway.get("/")
    fallback = gateway.get("/tickets/gateway-acceptance/deep-link")
    for response in (homepage, fallback):
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/html")
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["x-frame-options"] == "SAMEORIGIN"
        assert response.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert b"<!doctype html>" in homepage.content.lower()
    assert b'<div id="app"' in homepage.content
    assert fallback.content == homepage.content
    print("SPA: HTTP 200 for / and deep link, identical index.html, three security headers")


def test_websocket_handshake(gateway, agent):
    origin = str(gateway.base_url).rstrip("/")
    websocket_url = gateway.base_url.copy_with(
        scheme="wss" if gateway.base_url.scheme == "https" else "ws",
        path=f"/ws/message/default/{agent.username}",
    )
    with connect(str(websocket_url), origin=origin, additional_headers=agent.headers, open_timeout=10) as socket:
        assert socket.response.status_code == 101
        assert socket.response.headers["Upgrade"].lower() == "websocket"
        print("WebSocket: HTTP 101, Upgrade=websocket")
