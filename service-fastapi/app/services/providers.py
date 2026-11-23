from asyncio import sleep
from collections.abc import AsyncGenerator, AsyncIterator
from typing import Protocol

import httpx
from pydantic import BaseModel, Field, ValidationError

from app.core.config import Settings
from app.core.errors import ProviderError, invalid_output, provider_timeout
from app.schemas.context import TicketContext
from app.schemas.tickets import AnalysisDraft, Priority, unique_tags
from app.services import prompts


class LLMProvider(Protocol):
    model: str

    async def analyze(self, context: TicketContext) -> AnalysisDraft: ...

    # Async generators support closing the upstream response when the client disconnects.
    def stream_reply(self, context: TicketContext) -> AsyncGenerator[str]: ...


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

    async def stream_reply(self, context: TicketContext) -> AsyncGenerator[str]:
        await self._wait()
        title = context.ticket.title[:200]
        text = (
            f"您好，已收到您反馈的「{title}」。我们会核对问题发生时的环境和相关配置，"
            "并跟进处理进展。若方便，请补充问题出现的时间、操作步骤及可公开的报错信息。感谢您的配合。"
        )
        chunks = min(self.settings.mock_chunks, len(text))
        for index in range(chunks):
            if index:
                await sleep(self.settings.mock_chunk_delay)
            yield text[index * len(text) // chunks : (index + 1) * len(text) // chunks]


class CompletionMessage(BaseModel):
    content: str


class CompletionChoice(BaseModel):
    message: CompletionMessage


class Completion(BaseModel):
    choices: list[CompletionChoice] = Field(min_length=1)


class Delta(BaseModel):
    content: str | None = None


class StreamChoice(BaseModel):
    delta: Delta


class StreamChunk(BaseModel):
    choices: list[StreamChoice]


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

    def _payload(self, prompt: str, context: TicketContext) -> dict[str, object]:
        payload: dict[str, object] = {"model": self.model, "messages": prompts.messages(prompt, context)}
        if self.thinking != "default":
            payload["thinking"] = {"type": self.thinking}
        return payload

    async def analyze(self, context: TicketContext) -> AnalysisDraft:
        payload = self._payload(prompts.ANALYSIS_PROMPT, context)
        payload["response_format"] = {"type": "json_object"}
        try:
            response = await self.http.post(self.url, headers=self.headers, json=payload, timeout=self.timeout)
            _check_status(response)
            completion = Completion.model_validate_json(response.content)
            return AnalysisDraft.model_validate_json(completion.choices[0].message.content)
        except httpx.RequestError as exc:
            raise _request_error(exc) from exc
        except ValidationError as exc:
            raise invalid_output() from exc

    async def stream_reply(self, context: TicketContext) -> AsyncGenerator[str]:
        payload = self._payload(prompts.REPLY_PROMPT, context)
        payload["stream"] = True
        headers = {**self.headers, "Accept": "text/event-stream"}
        try:
            async with self.http.stream(
                "POST", self.url, headers=headers, json=payload, timeout=self.timeout
            ) as response:
                _check_status(response)
                async for data in _sse_data(response.aiter_lines()):
                    if data == "[DONE]":
                        return
                    chunk = StreamChunk.model_validate_json(data)
                    for choice in chunk.choices:
                        if choice.delta.content:
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
