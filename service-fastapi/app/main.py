from asyncio import Semaphore
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from redis.asyncio import Redis
from redis.asyncio.retry import Retry
from redis.backoff import NoBackoff

from app.api import assistant, health, tickets
from app.core.config import Settings
from app.core.errors import register_error_handlers
from app.core.request_id import RequestIdMiddleware
from app.core.resources import Resources
from app.services.providers import build_provider


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = Settings()
    http_timeout = httpx.Timeout(
        settings.http_read_timeout,
        connect=settings.http_connect_timeout,
        pool=settings.upstream_slot_timeout,
    )
    http_limits = httpx.Limits(
        max_connections=settings.http_max_connections,
        max_keepalive_connections=settings.http_max_connections,
    )
    async with (
        httpx.AsyncClient(timeout=http_timeout, limits=http_limits, trust_env=False) as drf_http,
        httpx.AsyncClient(timeout=http_timeout, limits=http_limits, trust_env=False) as llm_http,
        Redis.from_url(
            str(settings.auth_redis_url),
            decode_responses=False,
            socket_connect_timeout=settings.auth_redis_timeout,
            socket_timeout=settings.auth_redis_timeout,
            retry=Retry(NoBackoff(), 0),
        ) as redis,
    ):
        provider = build_provider(settings, llm_http)
        app.state.resources = Resources(settings, drf_http, redis, Semaphore(settings.upstream_concurrency), provider)
        yield


def create_app() -> FastAPI:
    app = FastAPI(title="TicketFlow AI", lifespan=lifespan)
    app.add_middleware(RequestIdMiddleware)
    register_error_handlers(app)
    app.include_router(health.router, prefix="/ai/v1")
    app.include_router(tickets.router, prefix="/ai/v1")
    app.include_router(assistant.router, prefix="/ai/v1")
    return app


app = create_app()
