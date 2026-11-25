import json
from asyncio import Semaphore
from contextlib import asynccontextmanager

import httpx
import pytest
from conftest import TICKET
from redis.asyncio import Redis

from app.core.config import Settings
from app.core.resources import Resources
from app.schemas.assistant import AnswerInput
from app.schemas.context import TicketContext
from app.services import drf, prompts
from app.services.kb_draft import generate_kb_draft
from app.services.providers import MockProvider, OpenAICompatibleProvider, strip_json_fence

pytestmark = pytest.mark.anyio


@asynccontextmanager
async def make_resources(transport, **overrides):
    settings = Settings(drf_base_url="http://drf:8896", **overrides)
    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as http, Redis() as redis:
        yield Resources(settings, http, redis, Semaphore(2), MockProvider(settings))


def test_strip_json_fence_removes_markdown_code_wrapper():
    wrapped = '```json\n{"category": "NETWORK"}\n```'
    assert strip_json_fence(wrapped) == '{"category": "NETWORK"}'
    assert strip_json_fence('{"category": "NETWORK"}') == '{"category": "NETWORK"}'


async def test_drf_forwards_internal_secret_and_user_id_on_answer(context_response):
    seen_headers = {}

    def transport(request):
        seen_headers.update(dict(request.headers))
        return httpx.Response(200, json={"code": 1000, "data": {"assistant_message_id": str(TICKET)}})

    body = AnswerInput(user_message_id=TICKET, content="请重启客户端", references=[], status="complete")
    async with make_resources(transport, internal_api_secret="shared-secret-value") as resources:
        result = await drf.record_answer(resources, TICKET, body, "expired-jwt", user_id=42)

    assert result.assistant_message_id == TICKET
    assert seen_headers["x-internal-token"] == "shared-secret-value"
    assert seen_headers["x-internal-user-id"] == "42"
    assert "authorization" not in seen_headers


async def test_drf_reads_forward_user_jwt_without_service_identity(context_response):
    seen_headers = {}

    def transport(request):
        seen_headers.update(dict(request.headers))
        return httpx.Response(200, json=context_response)

    async with make_resources(transport, internal_api_secret="shared-secret-value") as resources:
        await drf.fetch_ticket_context(resources, TICKET, "user-jwt")

    assert seen_headers["authorization"] == "Bearer user-jwt"
    assert seen_headers["x-internal-token"] == "shared-secret-value"
    assert "x-internal-user-id" not in seen_headers


async def test_openai_provider_parses_fenced_json_and_kb_draft(context_response):
    context_response["data"]["recent_messages"] = [
        {"role": "submitter", "sender": "emp", "content": "报错 691", "created_time": "2026-11-25T10:00:00Z"}
    ]
    context = TicketContext.model_validate(context_response["data"])
    prompt_msgs = prompts.messages(prompts.REPLY_PROMPT, context)
    assert "recent_messages" in json.loads(prompt_msgs[1]["content"])

    fenced = (
        "```json\n"
        + json.dumps(
            {
                "title": "VPN 691 排查指南",
                "category": "NETWORK",
                "tags": ["VPN", "691"],
                "body_markdown": "## 问题现象\n\n报错 691\n\n## 排查步骤\n\n核对账号\n\n## 解决方案\n\n重置密码",
            },
            ensure_ascii=False,
        )
        + "\n```"
    )

    def transport(request):
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": fenced}}],
                "usage": {"prompt_tokens": 120, "completion_tokens": 80, "total_tokens": 200},
            },
        )

    settings = Settings(mock_llm=False, llm_api_key="test-key", llm_base_url="https://model.test/v1")
    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as http, Redis() as redis:
        provider = OpenAICompatibleProvider(settings, http)
        resources = Resources(settings, http, redis, Semaphore(2), provider)
        draft = await generate_kb_draft(resources, context)

    assert draft.ticket_id == TICKET
    assert draft.title == "VPN 691 排查指南"
    assert draft.category == "NETWORK"


def test_request_id_middleware_propagates_header(client):
    response = client.get("/ai/v1/health", headers={"X-Request-ID": "req-trace-123"})
    assert response.headers["x-request-id"] == "req-trace-123"
    generated = client.get("/ai/v1/health")
    assert generated.headers.get("x-request-id")
