import asyncio
import json
import logging
from collections.abc import AsyncGenerator
from contextlib import AsyncExitStack, aclosing

from anyio import CancelScope, create_task_group
from fastapi.responses import StreamingResponse
from starlette.types import Receive, Scope, Send

from app.core.errors import ProviderError, ServiceError, provider_timeout
from app.core.resources import Resources
from app.schemas.context import TicketContext
from app.schemas.tickets import StreamMeta, StreamReference
from app.services.retry import reacquire_slot

logger = logging.getLogger(__name__)


def _frame(event: str, data: str) -> str:
    return f"event: {event}\ndata: {data}\n\n"


def _error_frame(exc: ServiceError) -> str:
    return _frame(
        "error",
        json.dumps(
            {
                "code": exc.status_code,
                "error": exc.error,
                "detail": exc.detail,
                "retryable": exc.retryable if isinstance(exc, ProviderError) else exc.error == "UPSTREAM_BUSY",
            },
            ensure_ascii=False,
        ),
    )


async def _chunks(resources: Resources, context: TicketContext, slot: AsyncExitStack) -> AsyncGenerator[str]:
    started = False
    for attempt in range(2):
        try:
            async with aclosing(resources.provider.stream_reply(context)) as chunks:
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


async def reply_events(
    resources: Resources, context: TicketContext, slot: AsyncExitStack, deadline: float
) -> AsyncGenerator[str]:
    meta = StreamMeta(
        ticket_id=context.ticket.id,
        ticket_version=context.ticket.version,
        references=[StreamReference(article_id=ref.article_id, title=ref.title) for ref in context.references],
    )
    yield _frame("meta", meta.model_dump_json())

    chunks = _chunks(resources, context, slot)
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
                yield _frame("ping", "{}")
                continue
            text = pending.result()
            pending = None
            yield _frame("delta", json.dumps({"text": text}, ensure_ascii=False))
        yield _error_frame(provider_timeout())
    except StopAsyncIteration:
        yield _frame("done", '{"finish_reason":"stop"}')
    except ServiceError as exc:
        yield _error_frame(exc)
    except Exception:
        logger.exception("Unexpected reply stream failure")
        yield _error_frame(ServiceError(500, "INTERNAL_SERVER_ERROR", "服务内部错误"))
    finally:
        with CancelScope(shield=True):
            if pending is not None:
                pending.cancel()
                await asyncio.gather(pending, return_exceptions=True)
            await chunks.aclose()


class ReplyResponse(StreamingResponse):
    def __init__(self, events: AsyncGenerator[str], deadline: float) -> None:
        super().__init__(
            events,
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
        self.events = events
        self.deadline = deadline

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        async with create_task_group() as group:

            async def cancel_on_disconnect() -> None:
                await self.listen_for_disconnect(receive)
                group.cancel_scope.cancel()

            group.start_soon(cancel_on_disconnect)
            try:
                # A short grace period lets the timeout frame flush while bounding a stalled socket.
                async with asyncio.timeout_at(self.deadline + 1):
                    await self.stream_response(send)
            except OSError, TimeoutError:
                pass
            finally:
                group.cancel_scope.cancel()
                with CancelScope(shield=True):
                    await self.events.aclose()
