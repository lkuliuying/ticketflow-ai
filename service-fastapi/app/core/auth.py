from asyncio import timeout
from dataclasses import dataclass, field
from hashlib import md5
from typing import Annotated, Literal

import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field, StrictInt
from redis.exceptions import RedisError

from app.core.errors import AuthRedisUnavailable, ServiceError
from app.core.resources import AppResources, Resources

BearerCredentials = Annotated[HTTPAuthorizationCredentials | None, Depends(HTTPBearer(auto_error=False))]
NonEmptyString = Annotated[str, Field(min_length=1)]


class AccessClaims(BaseModel):
    exp: StrictInt
    iat: StrictInt
    jti: NonEmptyString
    user_id: NonEmptyString | StrictInt
    token_type: Literal["access"]
    sid: NonEmptyString | None = None


@dataclass(frozen=True, slots=True)
class AuthenticatedUser:
    user_id: str | int
    raw_token: str = field(repr=False)


def _unauthorized() -> ServiceError:
    return ServiceError(401, "UNAUTHORIZED", "需要有效的 Bearer access token", {"WWW-Authenticate": "Bearer"})


def _decode_access_token(raw_token: str, signing_key: str) -> AccessClaims:
    try:
        payload = jwt.decode(
            raw_token,
            signing_key,
            algorithms=["HS256"],
            audience="x",
            issuer="server",
            leeway=0,
            options={"require": ["exp", "iat", "jti", "user_id", "token_type"]},
        )
        return AccessClaims.model_validate(payload)
    except (jwt.InvalidTokenError, TypeError, ValueError, OverflowError) as exc:
        raise _unauthorized() from exc


async def _is_revoked(resources: Resources, claims: AccessClaims, raw_token: str) -> bool:
    digest = md5(raw_token.encode("utf-8"), usedforsecurity=False).hexdigest()
    keys = [f"black_access_token_{claims.user_id}_{digest}", f"user_token_revoked_{claims.user_id}"]
    if claims.sid:
        keys.append(f"session_token_revoked_{claims.sid}")

    try:
        async with timeout(resources.settings.auth_redis_timeout):
            values = await resources.redis.mget(keys)
        # DRF writes plain integers through Django Redis's integer fast path.
        blacklisted, revoked_at, *sessions = [int(value) if value is not None else 0 for value in values]
    except (RedisError, TimeoutError, ValueError) as exc:
        raise AuthRedisUnavailable() from exc
    return bool(blacklisted or (revoked_at and claims.iat <= revoked_at) or any(sessions))


async def get_current_user(credentials: BearerCredentials, resources: AppResources) -> AuthenticatedUser:
    if credentials is None:
        raise _unauthorized()
    raw_token = credentials.credentials.strip()
    claims = _decode_access_token(raw_token, resources.settings.jwt_signing_key.get_secret_value())
    if await _is_revoked(resources, claims, raw_token):
        raise _unauthorized()
    return AuthenticatedUser(claims.user_id, raw_token)
