from asyncio import sleep
from contextlib import AsyncExitStack
from random import uniform

from app.core.resources import Resources, upstream_slot


async def reacquire_slot(resources: Resources, slot: AsyncExitStack) -> None:
    await slot.aclose()
    await sleep(uniform(0, 0.1))
    await slot.enter_async_context(upstream_slot(resources))
