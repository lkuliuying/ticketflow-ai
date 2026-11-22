from asyncio import timeout

from fastapi import APIRouter
from redis.exceptions import RedisError

from app.core.errors import AuthRedisUnavailable
from app.core.resources import AppResources
from app.schemas.http import ErrorResponse, HealthResponse

router = APIRouter()


@router.get("/health", responses={503: {"model": ErrorResponse}})
async def health(resources: AppResources) -> HealthResponse:
    try:
        async with timeout(resources.settings.auth_redis_timeout):
            healthy = await resources.redis.ping()
    except (RedisError, TimeoutError) as exc:
        raise AuthRedisUnavailable() from exc
    if not healthy:
        raise AuthRedisUnavailable()
    return HealthResponse()
