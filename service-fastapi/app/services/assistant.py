import logging
from asyncio import timeout
from collections.abc import AsyncGenerator
from contextlib import AsyncExitStack, aclosing
from uuid import UUID

from anyio import CancelScope
from pydantic import ValidationError

from app.core.errors import ServiceError, invalid_output, provider_timeout
from app.core.resources import Resources, upstream_slot
from app.schemas.assistant import (
    MAX_ANSWER_LENGTH,
    AnswerInput,
    AnswerStatus,
    AssistantContext,
    ChatMeta,
    ChatRequest,
    HandoffDraft,
    QuestionContext,
)
from app.schemas.context import Reference
from app.services.drf import record_answer
from app.services.retry import generate_with_retry
from app.services.stream import error_frame, frame, stream_chunks

logger = logging.getLogger(__name__)


class ChatStream:
    def __init__(
        self, resources: Resources, body: ChatRequest, context: QuestionContext, raw_token: str, slot: AsyncExitStack
    ) -> None:
        self.resources = resources
        self.body = body
        self.context = context
        self.raw_token = raw_token
        self.slot = slot
        self.meta = ChatMeta(
            session_id=body.session_id,
            user_message_id=context.user_message_id,
            references=[Reference(article_id=ref.article_id, title=ref.title) for ref in context.references],
        )
        self.parts: list[str] = []
        self.length = 0
        self.terminal = False

    async def _store(self, status: AnswerStatus) -> UUID:
        self.terminal = True
        body = AnswerInput(
            user_message_id=self.meta.user_message_id,
            content="".join(self.parts),
            references=self.meta.references,
            status=status,
        )
        with CancelScope(shield=True):
            await self.slot.aclose()
            result = await record_answer(self.resources, self.meta.session_id, body, self.raw_token)
        return result.assistant_message_id

    async def _store_partial(self, status: AnswerStatus) -> None:
        try:
            await self._store(status)
        except ServiceError as exc:
            logger.warning("Could not store %s assistant answer: %s", status, exc.error)

    async def close(self) -> None:
        if not self.terminal:
            await self._store_partial("interrupted")

    async def events(self, deadline: float) -> AsyncGenerator[str]:
        yield frame("meta", self.meta)

        def source() -> AsyncGenerator[str]:
            return self.resources.provider.stream_chat(self.context, self.body.message)

        try:
            async with aclosing(stream_chunks(self.resources, source, self.slot, deadline)) as chunks:
                async for text in chunks:
                    if text is None:
                        yield frame("ping", {})
                        continue
                    self.length += len(text)
                    if self.length > MAX_ANSWER_LENGTH:
                        raise invalid_output()
                    self.parts.append(text)
                    yield frame("delta", {"text": text})
            if not "".join(self.parts).strip():
                raise invalid_output()
            answer_id = await self._store("complete")
            yield frame("done", {"finish_reason": "stop", "assistant_message_id": str(answer_id)})
        except ServiceError as exc:
            if not self.terminal:
                await self._store_partial("failed")
            yield error_frame(exc)
        except Exception:
            logger.exception("Unexpected assistant stream failure")
            if not self.terminal:
                await self._store_partial("failed")
            yield error_frame(ServiceError(500, "INTERNAL_SERVER_ERROR", "服务内部错误"))


async def generate_handoff_draft(resources: Resources, context: AssistantContext) -> HandoffDraft:
    async with AsyncExitStack() as slot:
        await slot.enter_async_context(upstream_slot(resources))
        try:
            async with timeout(resources.settings.llm_timeout):
                draft = await generate_with_retry(resources, slot, lambda: resources.provider.handoff_draft(context))
            draft = HandoffDraft.model_validate(draft)
            if draft.category not in context.categories:
                raise invalid_output()
            return draft
        except TimeoutError as exc:
            raise provider_timeout() from exc
        except ValidationError as exc:
            raise invalid_output() from exc
