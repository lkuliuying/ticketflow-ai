import asyncio
import json
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import AsyncExitStack, aclosing

from anyio import CancelScope, create_task_group
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from starlette.types import Receive, Scope, Send

from app.core.errors import ProviderError, ServiceError, provider_timeout
from app.core.resources import Resources
from app.services.retry import reacquire_slot

StreamSource = Callable[[], AsyncGenerator[str]]
SSE_CONTENT = {"text/event-stream": {"schema": {"type": "string"}}}


def frame(event: str, data: BaseModel | dict[str, object]) -> str:
    payload = data.model_dump_json() if isinstance(data, BaseModel) else json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n"


def error_frame(exc: ServiceError) -> str:
    return frame(
        "error",
        {
            "code": exc.status_code,
            "error": exc.error,
            "detail": exc.detail,
            "retryable": exc.retryable if isinstance(exc, ProviderError) else exc.error == "UPSTREAM_BUSY",
        },
    )


async def _chunks(resources: Resources, source: StreamSource, slot: AsyncExitStack) -> AsyncGenerator[str]:
    started = False
    for attempt in range(2):
        try:
            async with aclosing(source()) as chunks:
                async for text in chunks:
                    if text:
                        started = True
                        yield text
            return
        except ProviderError as exc:
            if started or attempt or not exc.retryable:
                raise
        await reacquire_slot(resources, slot)


async def _next(chunks: AsyncGenerator[str]) -> str:
    return await anext(chunks)


async def stream_chunks(
    resources: Resources, source: StreamSource, slot: AsyncExitStack, deadline: float
) -> AsyncGenerator[str | None]:
    chunks = _chunks(resources, source, slot)
    pending: asyncio.Task[str] | None = None
    clock = asyncio.get_running_loop().time
    try:
        while (remaining := deadline - clock()) > 0:
            if pending is None:
                pending = asyncio.create_task(_next(chunks))
            interval = min(remaining, resources.settings.stream_ping_interval)
            ready, _ = await asyncio.wait({pending}, timeout=interval)
            if deadline <= clock():
                break
            if not ready:
                yield None
                continue
            text = pending.result()
            pending = None
            yield text
        raise provider_timeout()
    except StopAsyncIteration:
        return
    finally:
        with CancelScope(shield=True):
            if pending is not None:
                pending.cancel()
                await asyncio.gather(pending, return_exceptions=True)
            await chunks.aclose()


class EventStreamResponse(StreamingResponse):
    def __init__(
        self, events: AsyncGenerator[str], deadline: float, *, on_close: Callable[[], Awaitable[None]] | None = None
    ) -> None:
        super().__init__(
            events,
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
        self.events = events
        self.deadline = deadline
        self.on_close = on_close

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        async with create_task_group() as group:

            async def cancel_on_disconnect() -> None:
                await self.listen_for_disconnect(receive)
                group.cancel_scope.cancel()

            group.start_soon(cancel_on_disconnect)
            try:
                # Give the terminal frame a short window to flush on a stalled socket.
                async with asyncio.timeout_at(self.deadline + 1):
                    await self.stream_response(send)
            except OSError, TimeoutError:
                pass
            finally:
                group.cancel_scope.cancel()
                with CancelScope(shield=True):
                    await self.events.aclose()
                    if self.on_close is not None:
                        await self.on_close()
