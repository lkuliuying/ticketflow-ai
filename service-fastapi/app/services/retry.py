from asyncio import sleep
from collections.abc import Awaitable, Callable
from contextlib import AsyncExitStack
from random import uniform

from app.core.errors import ProviderError
from app.core.resources import Resources, upstream_slot


async def reacquire_slot(resources: Resources, slot: AsyncExitStack) -> None:
    await slot.aclose()
    await sleep(uniform(0, 0.1))
    await slot.enter_async_context(upstream_slot(resources))


async def generate_with_retry[T](resources: Resources, slot: AsyncExitStack, generate: Callable[[], Awaitable[T]]) -> T:
    try:
        return await generate()
    except ProviderError as exc:
        if not exc.retryable:
            raise
    await reacquire_slot(resources, slot)
    return await generate()
