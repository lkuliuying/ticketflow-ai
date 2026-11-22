import os
from hashlib import md5
from unittest.mock import AsyncMock

import jwt
import pytest
from fastapi.testclient import TestClient
from redis import Redis
from redis.exceptions import ConnectionError, ResponseError, TimeoutError


def revocation_keys(claims, token):
    digest = md5(token.encode(), usedforsecurity=False).hexdigest()
    keys = [f"black_access_token_{claims['user_id']}_{digest}", f"user_token_revoked_{claims['user_id']}"]
    if "sid" in claims:
        keys.append(f"session_token_revoked_{claims['sid']}")
    return keys


@pytest.fixture
def mget(client, monkeypatch):
    mget = AsyncMock(side_effect=lambda keys: [None] * len(keys))
    monkeypatch.setattr(client.app.state.resources.redis, "mget", mget)
    return mget


@pytest.mark.parametrize("has_sid", [True, False])
def test_access_checks_exact_keys_in_one_mget(client, signing_key, claims, mget, has_sid):
    if not has_sid:
        del claims["sid"]
        claims["user_id"] = int(claims["user_id"])
    token = jwt.encode(claims, signing_key, algorithm="HS256")
    response = client.get("/ai/v1/protected", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert response.json()["user_id"] == claims["user_id"]
    mget.assert_awaited_once_with(revocation_keys(claims, token))


@pytest.mark.parametrize(
    ("claim", "value"),
    [
        ("token_type", "refresh"),
        ("exp", 0),
        ("iat", 2**32),
        ("aud", "other"),
        ("iss", "other"),
        ("iat", []),
        ("jti", ""),
        ("user_id", True),
    ],
)
def test_invalid_claims_are_rejected_before_redis(client, signing_key, claims, mget, claim, value):
    claims[claim] = value
    token = jwt.encode(claims, signing_key, algorithm="HS256")

    response = client.get("/ai/v1/protected", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 401
    assert response.json() == {"code": 401, "error": "UNAUTHORIZED", "detail": "需要有效的 Bearer access token"}
    assert response.headers["WWW-Authenticate"] == "Bearer"
    mget.assert_not_awaited()


@pytest.mark.parametrize("claim", ["aud", "iss", "jti", "exp", "iat", "user_id", "token_type"])
def test_required_claims(client, signing_key, claims, mget, claim):
    del claims[claim]
    token = jwt.encode(claims, signing_key, algorithm="HS256")

    response = client.get("/ai/v1/protected", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == response.json()["code"] == 401
    assert response.json()["error"] == "UNAUTHORIZED"
    mget.assert_not_awaited()


@pytest.mark.parametrize(
    ("algorithm", "key"),
    [("HS384", "expected"), ("none", None), ("HS256", "a-different-signing-key-with-32-bytes")],
)
def test_bad_signatures_and_algorithms(client, signing_key, claims, mget, algorithm, key):
    token = jwt.encode(claims, signing_key if key == "expected" else key, algorithm=algorithm)

    assert client.get("/ai/v1/protected", headers={"Authorization": f"Bearer {token}"}).status_code == 401
    mget.assert_not_awaited()


@pytest.mark.parametrize("authorization", [None, "Basic invalid", "Bearer invalid"])
def test_bad_authorization_header(client, mget, authorization):
    response = client.get("/ai/v1/protected", headers={"Authorization": authorization} if authorization else {})

    assert response.status_code == 401
    mget.assert_not_awaited()


@pytest.mark.parametrize(
    ("slot", "offset", "status"),
    [(0, None, 401), (1, -1, 200), (1, 0, 401), (1, 1, 401), (2, None, 401)],
)
def test_revocation_markers_and_timestamp(client, signing_key, claims, mget, slot, offset, status):
    token = jwt.encode(claims, signing_key, algorithm="HS256")
    values = [None, None, None]
    values[slot] = b"1" if offset is None else str(claims["iat"] + offset).encode()
    mget.side_effect = None
    mget.return_value = values

    assert client.get("/ai/v1/protected", headers={"Authorization": f"Bearer {token}"}).status_code == status
    mget.assert_awaited_once_with(revocation_keys(claims, token))


@pytest.mark.parametrize("error", [ConnectionError, TimeoutError, ResponseError])
def test_auth_redis_error_returns_503(client, signing_key, claims, mget, error):
    token = jwt.encode(claims, signing_key, algorithm="HS256")
    mget.side_effect = error("unavailable")

    response = client.get("/ai/v1/protected", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 503
    assert response.json() == {"code": 503, "error": "AUTH_REDIS_UNAVAILABLE", "detail": "认证 Redis 不可用"}


def test_corrupt_redis_value_fails_closed(client, signing_key, claims, mget):
    token = jwt.encode(claims, signing_key, algorithm="HS256")
    mget.side_effect = None
    mget.return_value = [None, b"invalid integer", None]

    assert client.get("/ai/v1/protected", headers={"Authorization": f"Bearer {token}"}).status_code == 503


@pytest.mark.integration
def test_health_and_auth_with_real_redis(application, monkeypatch, signing_key, claims):
    redis_url = os.environ.get("AUTH_TEST_REDIS_URL")
    if not redis_url:
        pytest.skip("set AUTH_TEST_REDIS_URL to run against the real test Redis")
    monkeypatch.setenv("AUTH_REDIS_URL", redis_url)
    token = jwt.encode(claims, signing_key, algorithm="HS256")
    headers = {"Authorization": f"Bearer {token}"}
    keys = revocation_keys(claims, token)
    with Redis.from_url(redis_url) as redis, TestClient(application) as client:
        assert client.get("/ai/v1/health").json() == {"status": "ok", "redis": "ok"}
        assert client.get("/ai/v1/protected", headers=headers).status_code == 200
        for key, value in zip(keys, [1, claims["iat"], 1], strict=True):
            redis.set(key, value, ex=60)
            try:
                response = client.get("/ai/v1/protected", headers=headers)
                assert response.status_code == response.json()["code"] == 401
                assert response.json()["error"] == "UNAUTHORIZED"
            finally:
                redis.delete(key)
            assert client.get("/ai/v1/protected", headers=headers).status_code == 200
