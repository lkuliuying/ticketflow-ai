import logging
import re
from asyncio import sleep
from collections.abc import AsyncGenerator, AsyncIterator
from time import monotonic
from typing import Protocol

import httpx
from pydantic import BaseModel, Field, ValidationError

from app.core.config import Settings
from app.core.errors import ProviderError, invalid_output, provider_timeout
from app.core.request_id import get_request_id
from app.schemas.assistant import MAX_HANDOFF_DESCRIPTION_LENGTH, AssistantContext, HandoffDraft, QuestionContext
from app.schemas.context import TicketContext
from app.schemas.tickets import AnalysisDraft, KbDraft, Priority, unique_tags
from app.services import prompts

logger = logging.getLogger(__name__)
JSON_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*\n?(.*?)\n?\s*```\s*$", re.DOTALL | re.IGNORECASE)


def strip_json_fence(raw: str) -> str:
    matched = JSON_FENCE_RE.match(raw)
    return matched.group(1).strip() if matched else raw.strip()


class LLMProvider(Protocol):
    model: str

    async def analyze(self, context: TicketContext) -> AnalysisDraft: ...

    async def kb_draft(self, context: TicketContext) -> KbDraft: ...

    # Async generators support closing the upstream response when the client disconnects.
    def stream_reply(self, context: TicketContext) -> AsyncGenerator[str]: ...

    def stream_chat(self, context: QuestionContext, question: str) -> AsyncGenerator[str]: ...

    async def handoff_draft(self, context: AssistantContext) -> HandoffDraft: ...


class MockProvider:
    model = "ticketflow-mock"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def _wait(self) -> None:
        mode = self.settings.mock_llm_mode
        if mode == "timeout":
            await sleep(float("inf"))
        if mode == "error":
            raise ProviderError(503, "LLM_UNAVAILABLE", "模型提供方暂时不可用", retryable=True)
        delay = self.settings.mock_first_delay
        if mode == "slow":
            delay = max(delay, self.settings.stream_ping_interval * 2)
        await sleep(delay)

    async def analyze(self, context: TicketContext) -> AnalysisDraft:
        await self._wait()
        ticket = context.ticket
        text = f"{ticket.title}：{ticket.description}".strip()
        category = ticket.category if ticket.category in context.categories else context.categories[0]
        priority: Priority = "P2"
        if any(word in text for word in ("全站", "全部用户", "生产中断")):
            priority = "P0"
        elif any(word in text for word in ("不可用", "故障", "无法", "紧急")):
            priority = "P1"
        elif any(word in text for word in ("咨询", "建议")):
            priority = "P3"
        tags = unique_tags(["工单", category[:64].strip()])
        if len(tags) == 1:
            tags.append("客服")
        return AnalysisDraft(category=category, suggested_priority=priority, summary=text[:4000], tags=tags)

    async def kb_draft(self, context: TicketContext) -> KbDraft:
        await self._wait()
        ticket = context.ticket
        category = ticket.category if ticket.category in context.categories else context.categories[0]
        steps = (
            "\n".join(f"- {item.sender}：{item.content}" for item in context.recent_messages[:10])
            or "- 请根据工单排查记录补充关键核查步骤。"
        )
        body = (
            f"## 问题现象\n\n{ticket.description}\n\n"
            f"## 排查步骤\n\n{steps}\n\n"
            "## 解决方案\n\n按排查结论完成修复并确认恢复。"
        )
        return KbDraft(
            title=ticket.title[:200],
            category=category,
            tags=unique_tags(["工单沉淀", category[:64].strip()]),
            body_markdown=body[:50000],
        )

    async def _split(self, text: str) -> AsyncGenerator[str]:
        await self._wait()
        chunks = min(self.settings.mock_chunks, len(text))
        for index in range(chunks):
            if index:
                await sleep(self.settings.mock_chunk_delay)
            yield text[index * len(text) // chunks : (index + 1) * len(text) // chunks]

    def stream_reply(self, context: TicketContext) -> AsyncGenerator[str]:
        title = context.ticket.title[:200]
        text = (
            f"您好，已收到您反馈的「{title}」。我们会核对问题发生时的环境和相关配置，"
            "并跟进处理进展。若方便，请补充问题出现的时间、操作步骤及可公开的报错信息。感谢您的配合。"
        )
        return self._split(text)

    def stream_chat(self, context: QuestionContext, question: str) -> AsyncGenerator[str]:
        text = prompts.NO_KNOWLEDGE_ANSWER
        if context.references:
            text = "可参考以下知识库内容：\n" + "\n".join(
                f"{index}. {ref.title}：{ref.excerpt}" for index, ref in enumerate(context.references, 1)
            )
        return self._split(text)

    async def handoff_draft(self, context: AssistantContext) -> HandoffDraft:
        await self._wait()
        question = next((turn.content for turn in reversed(context.history) if turn.role == "user"), "").strip()
        category = "OTHER" if "OTHER" in context.categories else context.categories[0]
        return HandoffDraft(
            title=question[:200] or "IT 支持请求",
            description=question[:MAX_HANDOFF_DESCRIPTION_LENGTH] or "请补充遇到的问题和已尝试的操作。",
            category=category,
        )


class UsageStats(BaseModel):
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None


class CompletionMessage(BaseModel):
    content: str


class CompletionChoice(BaseModel):
    message: CompletionMessage


class Completion(BaseModel):
    choices: list[CompletionChoice] = Field(min_length=1)
    usage: UsageStats | None = None


class Delta(BaseModel):
    content: str | None = None


class StreamChoice(BaseModel):
    delta: Delta


class StreamChunk(BaseModel):
    choices: list[StreamChoice]
    usage: UsageStats | None = None


async def _sse_data(lines: AsyncIterator[str]) -> AsyncIterator[str]:
    data: list[str] = []
    async for line in lines:
        if not line:
            if data:
                yield "\n".join(data)
                data.clear()
        elif line == "data" or line.startswith("data:"):
            data.append(line[5:].removeprefix(" "))
    if data:
        yield "\n".join(data)


def _request_error(exc: httpx.RequestError) -> ProviderError:
    retryable = isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout))
    if isinstance(exc, httpx.TimeoutException):
        return provider_timeout(retryable=retryable)
    return ProviderError(503, "LLM_UNAVAILABLE", "模型提供方暂时不可用", retryable=retryable)


def _check_status(response: httpx.Response) -> None:
    if response.is_success:
        return
    status = response.status_code
    retryable = status in {429, 500, 502, 503, 504}
    if status == 504:
        raise provider_timeout(retryable=retryable)
    raise ProviderError(503, "LLM_UNAVAILABLE", "模型提供方暂时不可用", retryable=retryable)


class OpenAICompatibleProvider:
    def __init__(self, settings: Settings, http: httpx.AsyncClient) -> None:
        self.http = http
        self.model = settings.llm_model
        self.thinking = settings.llm_thinking
        self.url = f"{str(settings.llm_base_url).rstrip('/')}/chat/completions"
        self.timeout = httpx.Timeout(
            settings.llm_timeout, connect=settings.http_connect_timeout, pool=settings.upstream_slot_timeout
        )
        if settings.llm_api_key is None:
            raise ValueError("LLM_API_KEY is required")
        self.headers = {"Authorization": f"Bearer {settings.llm_api_key.get_secret_value()}"}

    def _payload(self, messages: list[prompts.Message]) -> dict[str, object]:
        payload: dict[str, object] = {"model": self.model, "messages": messages}
        if self.thinking != "default":
            payload["thinking"] = {"type": self.thinking}
        return payload

    async def _complete[T: BaseModel](self, messages: list[prompts.Message], schema: type[T], operation: str) -> T:
        payload = self._payload(messages)
        payload["response_format"] = {"type": "json_object"}
        started = monotonic()
        try:
            response = await self.http.post(self.url, headers=self.headers, json=payload, timeout=self.timeout)
            _check_status(response)
            completion = Completion.model_validate_json(response.content)
            parsed = schema.model_validate_json(strip_json_fence(completion.choices[0].message.content))
            elapsed_ms = round((monotonic() - started) * 1000, 1)
            usage = completion.usage.model_dump() if completion.usage else None
            logger.info(
                "llm_complete operation=%s model=%s request_id=%s duration_ms=%s usage=%s",
                operation,
                self.model,
                get_request_id(),
                elapsed_ms,
                usage,
            )
            return parsed
        except httpx.RequestError as exc:
            raise _request_error(exc) from exc
        except ValidationError as exc:
            raise invalid_output() from exc

    async def analyze(self, context: TicketContext) -> AnalysisDraft:
        return await self._complete(prompts.messages(prompts.ANALYSIS_PROMPT, context), AnalysisDraft, "analyze")

    async def kb_draft(self, context: TicketContext) -> KbDraft:
        return await self._complete(prompts.kb_draft_messages(context), KbDraft, "kb_draft")

    async def handoff_draft(self, context: AssistantContext) -> HandoffDraft:
        return await self._complete(prompts.handoff_messages(context), HandoffDraft, "handoff_draft")

    def stream_reply(self, context: TicketContext) -> AsyncGenerator[str]:
        return self._stream(prompts.messages(prompts.REPLY_PROMPT, context), "stream_reply")

    def stream_chat(self, context: QuestionContext, question: str) -> AsyncGenerator[str]:
        return self._stream(prompts.chat_messages(context, question), "stream_chat")

    async def _stream(self, messages: list[prompts.Message], operation: str) -> AsyncGenerator[str]:
        payload = self._payload(messages)
        payload["stream"] = True
        headers = {**self.headers, "Accept": "text/event-stream"}
        started = monotonic()
        ttft_ms: float | None = None
        last_usage: UsageStats | None = None
        try:
            async with self.http.stream(
                "POST", self.url, headers=headers, json=payload, timeout=self.timeout
            ) as response:
                _check_status(response)
                async for data in _sse_data(response.aiter_lines()):
                    if data == "[DONE]":
                        elapsed_ms = round((monotonic() - started) * 1000, 1)
                        logger.info(
                            "llm_stream operation=%s model=%s request_id=%s ttft_ms=%s duration_ms=%s usage=%s",
                            operation,
                            self.model,
                            get_request_id(),
                            ttft_ms,
                            elapsed_ms,
                            last_usage.model_dump() if last_usage else None,
                        )
                        return
                    chunk = StreamChunk.model_validate_json(data)
                    if chunk.usage is not None:
                        last_usage = chunk.usage
                    for choice in chunk.choices:
                        if choice.delta.content:
                            if ttft_ms is None:
                                ttft_ms = round((monotonic() - started) * 1000, 1)
                            yield choice.delta.content
        except httpx.RequestError as exc:
            raise _request_error(exc) from exc
        except ValidationError as exc:
            raise invalid_output() from exc
        raise invalid_output()


def build_provider(settings: Settings, http: httpx.AsyncClient) -> LLMProvider:
    if settings.mock_llm:
        return MockProvider(settings)
    return OpenAICompatibleProvider(settings, http)
