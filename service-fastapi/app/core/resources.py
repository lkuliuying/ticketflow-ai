import asyncio
from dataclasses import dataclass
from typing import Annotated, cast

import httpx
from fastapi import Depends, Request
from redis.asyncio import Redis

from app.core.config import Settings


@dataclass(frozen=True, slots=True)
class Resources:
    settings: Settings
    http: httpx.AsyncClient
    redis: Redis
    upstream_slots: asyncio.Semaphore


def get_resources(request: Request) -> Resources:
    return cast(Resources, request.app.state.resources)


AppResources = Annotated[Resources, Depends(get_resources)]
