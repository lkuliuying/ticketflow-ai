import socket
from unittest.mock import AsyncMock

import jwt
from fastapi.testclient import TestClient
from redis.exceptions import ConnectionError


def test_health_uses_shared_clients_and_closes_them(application, monkeypatch):
    monkeypatch.setenv("MOCK_LLM", "false")
    monkeypatch.setenv("LLM_API_KEY", "test-only")
    with TestClient(application) as client:
        resources = application.state.resources
        llm_http = resources.provider.http
        ping = AsyncMock(return_value=True)
        monkeypatch.setattr(resources.redis, "ping", ping)
        close_redis = AsyncMock(wraps=resources.redis.aclose)
        monkeypatch.setattr(resources.redis, "aclose", close_redis)

        response = client.get("/ai/v1/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok", "redis": "ok"}
        assert client.get("/ai/v1/health").status_code == 200
        assert ping.await_count == 2
        assert resources.drf_http is not llm_http
        assert not resources.drf_http.is_closed
        assert not llm_http.is_closed

    assert resources.drf_http.is_closed
    assert llm_http.is_closed
    close_redis.assert_awaited_once()


def test_application_fixture_ignores_dotenv(application, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("DRF_MAX_RETRIES=0\nUPSTREAM_SLOT_TIMEOUT=0\n", encoding="utf-8")

    with TestClient(application):
        settings = application.state.resources.settings
        assert settings.drf_max_retries == 2
        assert settings.upstream_slot_timeout == 1.0


def test_health_redis_error_returns_503(client, monkeypatch):
    ping = AsyncMock(side_effect=ConnectionError("unavailable"))
    monkeypatch.setattr(client.app.state.resources.redis, "ping", ping)

    response = client.get("/ai/v1/health")

    assert response.status_code == 503
    assert response.json() == {"code": 503, "error": "AUTH_REDIS_UNAVAILABLE", "detail": "认证 Redis 不可用"}


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
    assert (
        health.json()
        == auth.json()
        == {
            "code": 503,
            "error": "AUTH_REDIS_UNAVAILABLE",
            "detail": "认证 Redis 不可用",
        }
    )


def test_http_errors_keep_string_detail_and_headers(client):
    response = client.post("/ai/v1/health")

    assert response.status_code == 405
    assert response.json() == {"code": 405, "error": "METHOD_NOT_ALLOWED", "detail": "Method Not Allowed"}
    assert response.headers["Allow"] == "GET"


def test_validation_error_uses_error_envelope(client, signing_key, claims, monkeypatch):
    monkeypatch.setattr(client.app.state.resources.redis, "mget", AsyncMock(return_value=[None, None, None]))
    token = jwt.encode(claims, signing_key, algorithm="HS256")

    response = client.get("/ai/v1/protected?ticket_id=invalid", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 422
    assert response.json()["code"] == 422
    assert response.json()["error"] == "VALIDATION_ERROR"
    assert response.json()["detail"].startswith("query.ticket_id: ")
    assert set(response.json()) == {"code", "error", "detail"}
