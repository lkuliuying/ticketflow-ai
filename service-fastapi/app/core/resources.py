import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Annotated, cast

import httpx
from fastapi import Depends, Request
from redis.asyncio import Redis

from app.core.config import Settings
from app.core.errors import ServiceError
from app.services.providers import LLMProvider


@dataclass(frozen=True, slots=True)
class Resources:
    settings: Settings
    http: httpx.AsyncClient
    redis: Redis
    upstream_slots: asyncio.Semaphore
    provider: LLMProvider


@asynccontextmanager
async def upstream_slot(resources: Resources) -> AsyncIterator[None]:
    try:
        async with asyncio.timeout(resources.settings.upstream_slot_timeout):
            await resources.upstream_slots.acquire()
    except TimeoutError as exc:
        raise ServiceError(503, "UPSTREAM_BUSY", "上游并发额度已用完") from exc

    try:
        yield
    finally:
        resources.upstream_slots.release()


def get_resources(request: Request) -> Resources:
    return cast(Resources, request.app.state.resources)


AppResources = Annotated[Resources, Depends(get_resources)]
