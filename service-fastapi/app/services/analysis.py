import json
import re
import unicodedata
from asyncio import timeout
from contextlib import AsyncExitStack
from hashlib import sha256

from pydantic import ValidationError
from redis.exceptions import RedisError

from app.core.errors import ProviderError, invalid_output, provider_timeout
from app.core.resources import Resources, upstream_slot
from app.schemas.context import TicketContext
from app.schemas.tickets import AnalysisDraft, AnalysisResponse
from app.services import prompts
from app.services.retry import reacquire_slot

CACHE_PREFIX = "ticketflow:ai:analysis"


def _hash(values: list[str]) -> str:
    return sha256(json.dumps(values, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def _normalize(text: str) -> str:
    return re.sub(r"[\s\u200b\ufeff]+", "", unicodedata.normalize("NFKC", text))


def analysis_cache_key(resources: Resources, user_id: str | int, context: TicketContext) -> str:
    ticket = context.ticket
    text = _hash([_normalize(value) for value in (ticket.title, ticket.description, ticket.category)])
    categories = _hash(sorted(set(context.categories)))
    digest = _hash([str(user_id), text, categories, resources.provider.model, prompts.PROMPT_VERSION])
    return f"{CACHE_PREFIX}:{digest}"


def _validate_category(draft: AnalysisDraft, context: TicketContext) -> AnalysisDraft:
    if draft.category not in context.categories:
        raise invalid_output()
    return draft


async def _read_cache(resources: Resources, key: str, context: TicketContext) -> AnalysisDraft | None:
    try:
        async with timeout(resources.settings.auth_redis_timeout):
            value = await resources.redis.get(key)
        if value is not None:
            return _validate_category(AnalysisDraft.model_validate_json(value), context)
    except RedisError, TimeoutError, ValidationError, ProviderError:
        return None
    return None


async def _write_cache(resources: Resources, key: str, draft: AnalysisDraft) -> None:
    try:
        async with timeout(resources.settings.auth_redis_timeout):
            await resources.redis.set(key, draft.model_dump_json(), ex=resources.settings.analysis_cache_ttl)
    except RedisError, TimeoutError:
        pass


async def _generate(resources: Resources, context: TicketContext) -> AnalysisDraft:
    async with AsyncExitStack() as slot:
        await slot.enter_async_context(upstream_slot(resources))
        try:
            async with timeout(resources.settings.llm_timeout):
                try:
                    draft = await resources.provider.analyze(context)
                except ProviderError as exc:
                    if not exc.retryable:
                        raise
                    await reacquire_slot(resources, slot)
                    draft = await resources.provider.analyze(context)
            return _validate_category(AnalysisDraft.model_validate(draft), context)
        except TimeoutError as exc:
            raise provider_timeout() from exc
        except ValidationError as exc:
            raise invalid_output() from exc


async def analyze_ticket(resources: Resources, user_id: str | int, context: TicketContext) -> AnalysisResponse:
    key = analysis_cache_key(resources, user_id, context)
    draft = await _read_cache(resources, key, context)
    if draft is None:
        draft = await _generate(resources, context)
        await _write_cache(resources, key, draft)
    return AnalysisResponse(
        **draft.model_dump(),
        ticket_id=context.ticket.id,
        ticket_version=context.ticket.version,
    )
