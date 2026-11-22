import socket
from unittest.mock import AsyncMock

import jwt
from fastapi.testclient import TestClient
from redis.exceptions import ConnectionError


def test_health_uses_shared_clients_and_closes_them(application, monkeypatch):
    with TestClient(application) as client:
        resources = application.state.resources
        ping = AsyncMock(return_value=True)
        monkeypatch.setattr(resources.redis, "ping", ping)
        close_redis = AsyncMock(wraps=resources.redis.aclose)
        monkeypatch.setattr(resources.redis, "aclose", close_redis)

        response = client.get("/ai/v1/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok", "redis": "ok"}
        assert client.get("/ai/v1/health").status_code == 200
        assert ping.await_count == 2
        assert not resources.http.is_closed

    assert resources.http.is_closed
    close_redis.assert_awaited_once()


def test_health_redis_error_returns_503(client, monkeypatch):
    ping = AsyncMock(side_effect=ConnectionError("unavailable"))
    monkeypatch.setattr(client.app.state.resources.redis, "ping", ping)

    response = client.get("/ai/v1/health")

    assert response.status_code == 503
    assert response.json() == {"code": "AUTH_REDIS_UNAVAILABLE", "detail": "认证 Redis 不可用"}


def test_unreachable_redis_rejects_health_and_valid_token(application, monkeypatch, signing_key, claims):
    token = jwt.encode(claims, signing_key, algorithm="HS256")
    with socket.socket() as unused_port:
        unused_port.bind(("127.0.0.1", 0))
        monkeypatch.setenv("AUTH_REDIS_URL", f"redis://127.0.0.1:{unused_port.getsockname()[1]}/1")
        monkeypatch.setenv("AUTH_REDIS_TIMEOUT", "0.1")
        with TestClient(application) as client:
            health = client.get("/ai/v1/health")
            auth = client.get("/ai/v1/protected", headers={"Authorization": f"Bearer {token}"})

    assert health.status_code == auth.status_code == 503
    assert health.json() == auth.json() == {"code": "AUTH_REDIS_UNAVAILABLE", "detail": "认证 Redis 不可用"}


def test_http_errors_keep_string_detail_and_headers(client):
    response = client.post("/ai/v1/health")

    assert response.status_code == 405
    assert response.json() == {"code": "METHOD_NOT_ALLOWED", "detail": "Method Not Allowed"}
    assert response.headers["Allow"] == "GET"


def test_validation_error_uses_error_envelope(client, signing_key, claims, monkeypatch):
    monkeypatch.setattr(client.app.state.resources.redis, "mget", AsyncMock(return_value=[None, None, None]))
    token = jwt.encode(claims, signing_key, algorithm="HS256")

    response = client.get("/ai/v1/protected?ticket_id=invalid", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
    assert response.json()["detail"].startswith("query.ticket_id: ")
    assert set(response.json()) == {"code", "detail"}
