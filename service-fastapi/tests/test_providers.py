import json

import httpx
import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.core.errors import ProviderError
from app.schemas.context import TicketContext
from app.services.providers import MockProvider, OpenAICompatibleProvider

pytestmark = pytest.mark.anyio


@pytest.fixture
def context(context_response):
    return TicketContext.model_validate(context_response["data"])


@pytest.fixture
def settings():
    return Settings(
        mock_llm=False, llm_api_key="test-upstream-key", llm_base_url="https://model.test/v1", llm_model="test-model"
    )


async def test_mock_uses_permitted_category_and_is_deterministic(context):
    provider = MockProvider(Settings(mock_first_delay=0, mock_chunk_delay=0, mock_chunks=20))
    context.categories = ["OTHER"]
    draft = await provider.analyze(context)
    assert draft == await provider.analyze(context)
    assert draft.category == "OTHER"
    assert draft.suggested_priority == "P1"
    assert 2 <= len(draft.tags) <= 5
    chunks = [chunk async for chunk in provider.stream_reply(context)]
    assert len(chunks) == 20
    assert context.ticket.title in "".join(chunks)


async def test_real_provider_requires_a_key():
    with pytest.raises(ValidationError, match="LLM_API_KEY is required"):
        Settings(mock_llm=False)


async def test_completion_sends_only_authorized_content_and_parses_output(settings, context):
    def transport(request):
        assert request.url == "https://model.test/v1/chat/completions"
        assert request.headers["Authorization"] == "Bearer test-upstream-key"
        assert request.extensions["timeout"]["read"] == settings.llm_timeout
        payload = json.loads(request.content)
        assert payload["model"] == "test-model"
        assert payload["response_format"] == {"type": "json_object"}
        assert json.loads(payload["messages"][1]["content"]) == {
            "title": context.ticket.title,
            "description": context.ticket.description,
            "category": "NETWORK",
            "categories": context.categories,
            "references": [{"title": "VPN 排障", "excerpt": "检查入口地址"}],
        }
        content = {"category": "NETWORK", "suggested_priority": "P1", "summary": "VPN 故障", "tags": ["VPN", "VPN"]}
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(content)}}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as http:
        draft = await OpenAICompatibleProvider(settings, http).analyze(context)

    assert draft.summary == "VPN 故障"
    assert draft.tags == ["VPN"]


@pytest.mark.parametrize(
    ("status", "content", "code", "retryable"), [(200, "bad JSON", 502, False), (429, "", 503, True)]
)
async def test_completion_errors_are_mapped(settings, context, status, content, code, retryable):
    def transport(request):
        return httpx.Response(status, json={"choices": [{"message": {"content": content}}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as http:
        with pytest.raises(ProviderError) as raised:
            await OpenAICompatibleProvider(settings, http).analyze(context)
    assert raised.value.status_code == code
    assert raised.value.retryable is retryable


async def test_upstream_sse_parses_comments_roles_and_multiline_data(settings, context):
    def transport(request):
        assert json.loads(request.content)["stream"] is True
        assert request.headers["Accept"] == "text/event-stream"
        return httpx.Response(
            200,
            text=(
                ': comment\r\n\r\ndata: {"choices":[{"delta":{"role":"assistant"}}]}\r\n\r\n'
                'data: {"choices":\r\ndata: [{"delta":{"content":"您好"}}]}\r\n\r\n'
                'data: {"choices":[{"delta":{"content":"。"}}]}\r\n\r\n'
                'data: {"choices":[]}\r\n\r\ndata: [DONE]\r\n\r\n'
            ),
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as http:
        texts = [text async for text in OpenAICompatibleProvider(settings, http).stream_reply(context)]
    assert texts == ["您好", "。"]


async def test_truncated_upstream_sse_fails(settings, context):
    def transport(request):
        return httpx.Response(200, text='data: {"choices":[{"delta":{"content":"partial"}}]}\n\n')

    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as http:
        stream = OpenAICompatibleProvider(settings, http).stream_reply(context)
        assert await anext(stream) == "partial"
        with pytest.raises(ProviderError) as raised:
            await anext(stream)
    assert raised.value.error == "LLM_INVALID_OUTPUT"
