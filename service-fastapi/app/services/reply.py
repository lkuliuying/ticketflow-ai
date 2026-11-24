import logging
from collections.abc import AsyncGenerator
from contextlib import AsyncExitStack, aclosing

from app.core.errors import ServiceError
from app.core.resources import Resources
from app.schemas.context import Reference, TicketContext
from app.schemas.tickets import StreamMeta
from app.services.stream import error_frame, frame, stream_chunks

logger = logging.getLogger(__name__)


async def reply_events(
    resources: Resources, context: TicketContext, slot: AsyncExitStack, deadline: float
) -> AsyncGenerator[str]:
    meta = StreamMeta(
        ticket_id=context.ticket.id,
        ticket_version=context.ticket.version,
        references=[Reference(article_id=ref.article_id, title=ref.title) for ref in context.references],
    )
    yield frame("meta", meta)

    try:
        async with aclosing(
            stream_chunks(resources, lambda: resources.provider.stream_reply(context), slot, deadline)
        ) as chunks:
            async for text in chunks:
                yield frame("ping", {}) if text is None else frame("delta", {"text": text})
        yield frame("done", {"finish_reason": "stop"})
    except ServiceError as exc:
        yield error_frame(exc)
    except Exception:
        logger.exception("Unexpected reply stream failure")
        yield error_frame(ServiceError(500, "INTERNAL_SERVER_ERROR", "服务内部错误"))
