import asyncio
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack
from typing import Annotated, Any

from fastapi import APIRouter, Depends

from app.core.auth import AuthenticatedUser, get_current_user
from app.core.resources import AppResources, upstream_slot
from app.schemas.context import TicketContext
from app.schemas.http import ErrorResponse
from app.schemas.tickets import AnalysisResponse, TicketRequest
from app.services.analysis import analyze_ticket
from app.services.drf import fetch_ticket_context
from app.services.reply import reply_events
from app.services.stream import SSE_CONTENT, EventStreamResponse

router = APIRouter(prefix="/tickets", tags=["tickets"])
CurrentUser = Annotated[AuthenticatedUser, Depends(get_current_user)]
ERRORS: dict[int | str, dict[str, Any]] = {
    status: {"model": ErrorResponse} for status in (401, 403, 404, 422, 429, 500, 503, 504)
}


@router.post("/analyze", responses={**ERRORS, 502: {"model": ErrorResponse}})
async def analyze(body: TicketRequest, user: CurrentUser, resources: AppResources) -> AnalysisResponse:
    context = await fetch_ticket_context(resources, body.ticket_id, user.raw_token)
    return await analyze_ticket(resources, user.user_id, context)


async def _reply_context(
    body: TicketRequest, user: CurrentUser, resources: AppResources
) -> AsyncIterator[tuple[TicketContext, AsyncExitStack]]:
    context = await fetch_ticket_context(resources, body.ticket_id, user.raw_token)
    async with AsyncExitStack() as slot:
        await slot.enter_async_context(upstream_slot(resources))
        yield context, slot


@router.post(
    "/suggest-reply/stream",
    status_code=200,
    response_class=EventStreamResponse,
    responses={**ERRORS, 200: {"content": SSE_CONTENT}},
)
async def suggest_reply(
    prepared: Annotated[tuple[TicketContext, AsyncExitStack], Depends(_reply_context)],
    resources: AppResources,
) -> EventStreamResponse:
    context, slot = prepared
    deadline = asyncio.get_running_loop().time() + resources.settings.stream_timeout
    return EventStreamResponse(reply_events(resources, context, slot, deadline), deadline)
