from datetime import UTC, datetime, timedelta

import pytest
from django.core.cache import cache
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.state import token_backend

from common.cache.storage import BlackAccessTokenCache, SessionTokenRevokedCache, UserTokenRevokedCache
from common.core.auth.authentication import ServerAccessToken, ServerRefreshToken


@pytest.mark.django_db
@pytest.mark.parametrize("token_class", [ServerAccessToken, ServerRefreshToken])
@pytest.mark.parametrize(
    ("leeway", "claim", "offset", "accepted"),
    [
        (0, "iat", 20, False),
        (30, "iat", 15, True),
        (30, "iat", 120, False),
        (30, "exp", -15, True),
        (30, "exp", -120, False),
        (30, "nbf", 15, False),
    ],
)
def test_clock_leeway_applies_to_issue_and_expiration_times(monkeypatch, token_class, leeway, claim, offset, accepted):
    monkeypatch.setattr(token_backend, "leeway", leeway)
    token = token_class()
    token["user_id"] = "123456"
    token[claim] = int(datetime.now(UTC).timestamp()) + offset
    encoded = str(token)

    if accepted:
        assert token_class(encoded)[claim] == token[claim]
    else:
        with pytest.raises(TokenError):
            token_class(encoded)


@pytest.mark.parametrize("leeway", [30, timedelta(seconds=30)])
def test_access_revocation_covers_expiration_grace(settings, monkeypatch, leeway):
    settings.SIMPLE_JWT = {**settings.SIMPLE_JWT, "LEEWAY": leeway}
    monkeypatch.setattr("common.cache.storage.time", lambda: 1000.25)
    blacklist = BlackAccessTokenCache("123456", "clock-test")
    blacklist.revoke_until(995)
    assert blacklist.get_storage_cache() == 1
    assert 24 <= cache.ttl(blacklist.cache_key) <= 25


@pytest.mark.parametrize("cache_class", [UserTokenRevokedCache, SessionTokenRevokedCache])
def test_wide_leeway_preserves_revocation_for_full_token_lifetime(settings, cache_class):
    settings.SIMPLE_JWT = {**settings.SIMPLE_JWT, "LEEWAY": 120}
    revoked = cache_class("123456")
    revoked.set_storage_cache(1)
    lifetime = int(settings.SIMPLE_JWT["ACCESS_TOKEN_LIFETIME"].total_seconds())
    assert cache.ttl(revoked.cache_key) >= lifetime + 239
