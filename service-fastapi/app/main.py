from asyncio import Semaphore
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from redis.asyncio import Redis
from redis.asyncio.retry import Retry
from redis.backoff import NoBackoff

from app.api.health import router
from app.core.config import Settings
from app.core.errors import register_error_handlers
from app.core.resources import Resources


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = Settings()
    async with (
        httpx.AsyncClient(
            timeout=httpx.Timeout(
                settings.http_read_timeout,
                connect=settings.http_connect_timeout,
                pool=settings.upstream_slot_timeout,
            ),
            limits=httpx.Limits(
                max_connections=settings.http_max_connections,
                max_keepalive_connections=settings.http_max_connections,
            ),
            trust_env=False,
        ) as http,
        Redis.from_url(
            str(settings.auth_redis_url),
            decode_responses=False,
            socket_connect_timeout=settings.auth_redis_timeout,
            socket_timeout=settings.auth_redis_timeout,
            retry=Retry(NoBackoff(), 0),
        ) as redis,
    ):
        app.state.resources = Resources(settings, http, redis, Semaphore(settings.upstream_concurrency))
        yield


def create_app() -> FastAPI:
    app = FastAPI(title="TicketFlow AI", lifespan=lifespan)
    register_error_handlers(app)
    app.include_router(router, prefix="/ai/v1")
    return app


app = create_app()
