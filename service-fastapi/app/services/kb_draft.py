from asyncio import timeout
from contextlib import AsyncExitStack

from pydantic import ValidationError

from app.core.errors import invalid_output, provider_timeout
from app.core.resources import Resources, upstream_slot
from app.schemas.context import TicketContext
from app.schemas.tickets import KbDraft, KbDraftResponse
from app.services.retry import generate_with_retry


async def generate_kb_draft(resources: Resources, context: TicketContext) -> KbDraftResponse:
    async with AsyncExitStack() as slot:
        await slot.enter_async_context(upstream_slot(resources))
        try:
            async with timeout(resources.settings.llm_timeout):
                draft = await generate_with_retry(resources, slot, lambda: resources.provider.kb_draft(context))
            validated = KbDraft.model_validate(draft)
            if validated.category not in context.categories:
                raise invalid_output()
            return KbDraftResponse(**validated.model_dump(), ticket_id=context.ticket.id)
        except TimeoutError as exc:
            raise provider_timeout() from exc
        except ValidationError as exc:
            raise invalid_output() from exc
