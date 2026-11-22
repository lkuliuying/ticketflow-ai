"""Observe the upstream semaphore in the benchmark process only."""

from asyncio import Semaphore, get_running_loop
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import replace

from app.main import create_app
from starlette.datastructures import MutableHeaders

queue_ms = ContextVar("queue_ms", default=None)


class MeasuredSemaphore(Semaphore):
    def __init__(self, capacity):
        super().__init__(capacity)
        self.capacity = capacity
        self.in_use = 0
        self.waiting = 0

    async def acquire(self):
        clock = get_running_loop().time
        start = clock()
        self.waiting += 1
        try:
            acquired = await super().acquire()
            self.in_use += 1
            return acquired
        finally:
            self.waiting -= 1
            queue_ms.set((clock() - start) * 1000)

    def release(self):
        super().release()
        self.in_use -= 1


class QueueTiming:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        token = queue_ms.set(None)

        async def send_timing(message):
            if message["type"] == "http.response.start" and (elapsed := queue_ms.get()) is not None:
                MutableHeaders(scope=message).append("Server-Timing", f"upstream-queue;dur={elapsed:.3f}")
            await send(message)

        try:
            await self.app(scope, receive, send_timing)
        finally:
            queue_ms.reset(token)


app = create_app()
original_lifespan = app.router.lifespan_context


@asynccontextmanager
async def measured_lifespan(app):
    async with original_lifespan(app):
        resources = app.state.resources
        slots = MeasuredSemaphore(resources.settings.upstream_concurrency)
        app.state.resources = replace(resources, upstream_slots=slots)
        yield


app.router.lifespan_context = measured_lifespan
app.add_middleware(QueueTiming)


@app.get("/ai/v1/load-slots", include_in_schema=False)
async def slot_state():
    slots = app.state.resources.upstream_slots
    return {
        "capacity": slots.capacity,
        "in_use": slots.in_use,
        "available": slots.capacity - slots.in_use,
        "waiting": slots.waiting,
    }
