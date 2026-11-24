import asyncio
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack
from typing import Annotated, Any

from fastapi import APIRouter, Depends

from app.core.auth import AuthenticatedUser, get_current_user
from app.core.resources import AppResources, upstream_slot
from app.schemas.assistant import ChatRequest, HandoffDraft, HandoffRequest
from app.schemas.http import ErrorResponse
from app.services.assistant import ChatStream, generate_handoff_draft
from app.services.drf import fetch_assistant_context, record_question
from app.services.stream import SSE_CONTENT, EventStreamResponse

router = APIRouter(prefix="/assistant", tags=["assistant"])
CurrentUser = Annotated[AuthenticatedUser, Depends(get_current_user)]
ERRORS: dict[int | str, dict[str, Any]] = {
    status: {"model": ErrorResponse} for status in (400, 401, 403, 404, 409, 422, 429, 500, 503, 504)
}


async def prepare_chat(body: ChatRequest, user: CurrentUser, resources: AppResources) -> AsyncIterator[ChatStream]:
    async with AsyncExitStack() as slot:
        # Reserve capacity before creating a question so a full queue leaves no unanswered turn.
        await slot.enter_async_context(upstream_slot(resources))
        context = await record_question(resources, body, user.raw_token)
        yield ChatStream(resources, body, context, user.raw_token, slot)


@router.post(
    "/chat/stream",
    status_code=200,
    response_class=EventStreamResponse,
    responses={
        **ERRORS,
        200: {"content": SSE_CONTENT},
        409: {"model": ErrorResponse, "description": "会话已转人工，请新建对话"},
    },
)
async def chat(stream: Annotated[ChatStream, Depends(prepare_chat)], resources: AppResources) -> EventStreamResponse:
    deadline = asyncio.get_running_loop().time() + resources.settings.stream_timeout
    return EventStreamResponse(
        stream.events(deadline), deadline + resources.settings.drf_total_timeout, on_close=stream.close
    )


@router.post("/handoff-draft", responses={**ERRORS, 502: {"model": ErrorResponse}})
async def handoff_draft(body: HandoffRequest, user: CurrentUser, resources: AppResources) -> HandoffDraft:
    context = await fetch_assistant_context(resources, body.session_id, user.raw_token)
    return await generate_handoff_draft(resources, context)
