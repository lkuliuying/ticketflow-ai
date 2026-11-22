import asyncio
import json
import os
from dataclasses import replace
from uuid import uuid4

import httpx
import jwt
import pytest
from conftest import ARTICLE, TICKET
from redis.asyncio import Redis
from redis.exceptions import ConnectionError as RedisConnectionError

from app.core.config import Settings
from app.core.errors import ProviderError
from app.core.resources import Resources
from app.schemas.context import TicketContext
from app.schemas.tickets import AnalysisDraft
from app.services import prompts, retry
from app.services.analysis import analysis_cache_key
from app.services.providers import OpenAICompatibleProvider

ANALYZE = "/ai/v1/tickets/analyze"
STREAM = "/ai/v1/tickets/suggest-reply/stream"
pytestmark = pytest.mark.anyio


class InMemoryRedis:
    def __init__(self):
        self.values: dict[bytes, bytes] = {}
        self.reads = 0
        self.ttls = []
        self.outage = False

    async def mget(self, keys):
        return [None for _ in keys]

    async def get(self, key):
        self.reads += 1
        if self.outage:
            raise RedisConnectionError
        return self.values.get(key.encode())

    async def set(self, key, value, *, ex):
        if self.outage:
            raise RedisConnectionError
        self.values[key.encode()] = value.encode()
        self.ttls.append(ex)


class ControlledProvider:
    model = "test-model"

    def __init__(self):
        self.analyzed = 0
        self.streamed = 0
        self.draft = AnalysisDraft(category="NETWORK", suggested_priority="P1", summary="摘要", tags=["VPN", " VPN "])

    async def analyze(self, context):
        self.analyzed += 1
        return self.draft

    async def stream_reply(self, context):
        self.streamed += 1
        yield "您好"
        yield "。"


@pytest.fixture
async def harness(application, signing_key, claims, context_response):
    status = 200
    calls = []

    def upstream(request):
        calls.append(request)
        return httpx.Response(status, json=context_response if status == 200 else {"detail": "权限错误"})

    def set_status(value):
        nonlocal status
        status = value

    def bearer(**overrides):
        token = jwt.encode({**claims, **overrides}, signing_key, algorithm="HS256")
        return {"Authorization": f"Bearer {token}"}

    async with (
        httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as drf_http,
        httpx.AsyncClient(transport=httpx.ASGITransport(app=application), base_url="http://ai") as ai,
    ):
        settings = Settings(
            drf_base_url="http://drf", mock_first_delay=0, mock_chunk_delay=0, upstream_slot_timeout=0.02
        )
        resources = Resources(settings, drf_http, InMemoryRedis(), asyncio.Semaphore(1), ControlledProvider())
        application.state.resources = resources
        yield ai, application, resources, bearer, calls, set_status


async def test_cache_rechecks_drf_and_uses_current_ticket(harness, context_response):
    http, _, resources, bearer, calls, set_status = harness
    body = {"ticket_id": str(TICKET)}
    first = await http.post(ANALYZE, json=body, headers=bearer())
    assert first.json() == {
        "ticket_id": str(TICKET),
        "ticket_version": 2,
        "category": "NETWORK",
        "suggested_priority": "P1",
        "summary": "摘要",
        "tags": ["VPN"],
    }
    assert resources.redis.ttls == [600]

    other_ticket = str(uuid4())
    context_response["data"]["ticket"].update(id=other_ticket, title="ＶＰＮ\n无法 连接", version=9)
    body["ticket_id"] = other_ticket
    async with resources.upstream_slots:
        assert resources.upstream_slots.locked()
        hit = await http.post(ANALYZE, json=body, headers=bearer())
        assert hit.status_code == 200
        assert hit.json() == {**first.json(), "ticket_id": other_ticket, "ticket_version": 9}

        for status in (403, 404):
            set_status(status)
            denied = await http.post(ANALYZE, json=body, headers=bearer())
            assert denied.status_code == status
            assert denied.json()["code"] == status
    assert resources.redis.reads == 2
    assert len(calls) == 4
    assert resources.provider.analyzed == 1


@pytest.mark.integration
async def test_analysis_writes_and_reads_real_redis_cache(harness, context_response, claims):
    redis_url = os.environ.get("AUTH_TEST_REDIS_URL")
    if not redis_url:
        pytest.skip("set AUTH_TEST_REDIS_URL to run against the real test Redis")

    http, application, resources, bearer, calls, _ = harness
    context = TicketContext.model_validate(context_response["data"])
    key = analysis_cache_key(resources, claims["user_id"], context)
    body = {"ticket_id": str(TICKET)}
    headers = bearer()

    async with Redis.from_url(redis_url, decode_responses=False) as redis:
        application.state.resources = replace(resources, redis=redis)
        try:
            assert await redis.get(key) is None
            miss = await http.post(ANALYZE, json=body, headers=headers)
            assert miss.status_code == 200
            cached = await redis.get(key)
            assert isinstance(cached, bytes)
            assert AnalysisDraft.model_validate_json(cached) == resources.provider.draft
            assert 0 < await redis.ttl(key) <= resources.settings.analysis_cache_ttl

            async with resources.upstream_slots:
                hit = await http.post(ANALYZE, json=body, headers=headers)
            assert hit.status_code == 200
            assert hit.json() == miss.json()
            assert resources.provider.analyzed == 1
            assert len(calls) == 2
        finally:
            await redis.delete(key)


async def test_cache_keys_bind_user_text_categories_model_and_prompt(harness, context_response, monkeypatch):
    http, _, resources, bearer, _, _ = harness
    body = {"ticket_id": str(TICKET)}

    async def post(**overrides):
        result = await http.post(ANALYZE, json=body, headers=bearer(**overrides))
        assert result.status_code == 200

    await post()
    await post(user_id="other")
    context_response["data"]["ticket"]["description"] = "新的错误"
    await post()
    context_response["data"]["categories"].append("SERVICE")
    await post()
    context_response["data"]["categories"].reverse()
    await post()
    resources.provider.model = "test-model-2"
    await post()
    monkeypatch.setattr(prompts, "PROMPT_VERSION", "new-prompt")
    await post()
    assert resources.provider.analyzed == len(resources.redis.values) == 6


@pytest.mark.parametrize(
    "invalid",
    [
        {"category": "SERVICE"},
        {"summary": "x" * 4001},
        {"tags": ["x" * 65]},
        {"tags": [str(i) for i in range(13)]},
        {"suggested_priority": "P4"},
    ],
)
async def test_invalid_output_is_never_cached(harness, invalid):
    http, _, resources, bearer, _, _ = harness
    values = {**resources.provider.draft.model_dump(), **invalid}
    resources.provider.draft = AnalysisDraft.model_construct(**values)
    result = await http.post(ANALYZE, json={"ticket_id": str(TICKET)}, headers=bearer())
    assert result.status_code == 502
    assert result.json()["error"] == "LLM_INVALID_OUTPUT"
    assert not resources.redis.values


async def test_analysis_cache_outage_falls_through(harness):
    http, _, resources, bearer, _, _ = harness
    resources.redis.outage = True
    result = await http.post(ANALYZE, json={"ticket_id": str(TICKET)}, headers=bearer())
    assert result.status_code == 200
    assert resources.provider.analyzed == 1


@pytest.mark.parametrize("path", [ANALYZE, STREAM])
async def test_provider_slot_timeout_is_json_before_generation(harness, path):
    http, _, resources, bearer, calls, _ = harness
    async with resources.upstream_slots:
        result = await http.post(path, json={"ticket_id": str(TICKET)}, headers=bearer())
        assert resources.upstream_slots.locked()
    assert result.status_code == 503
    assert result.json()["error"] == "UPSTREAM_BUSY"
    assert len(calls) == 1
    assert resources.provider.analyzed == resources.provider.streamed == 0


async def test_analysis_provider_deadline_releases_slot(harness, monkeypatch):
    http, application, resources, bearer, _, _ = harness
    settings = resources.settings.model_copy(update={"llm_timeout": 0.02})
    application.state.resources = replace(resources, settings=settings)

    async def analyze(context):
        await asyncio.Future()

    monkeypatch.setattr(resources.provider, "analyze", analyze)
    result = await http.post(ANALYZE, json={"ticket_id": str(TICKET)}, headers=bearer())
    assert result.status_code == 504
    assert result.json()["error"] == "LLM_TIMEOUT"
    assert not resources.upstream_slots.locked()


def frames(body):
    return [
        (event[7:], json.loads(data[6:])) for event, data in (raw.splitlines() for raw in body.strip().split("\n\n"))
    ]


async def test_reply_frames_headers_and_openapi(harness):
    http, _, resources, bearer, _, _ = harness
    result = await http.post(STREAM, json={"ticket_id": str(TICKET)}, headers=bearer())
    assert result.status_code == 200
    assert result.headers["content-type"].startswith("text/event-stream")
    assert result.headers["cache-control"] == "no-cache"
    assert result.headers["x-accel-buffering"] == "no"
    assert frames(result.text) == [
        ("meta", {"ticket_id": str(TICKET), "ticket_version": 2, "references": [str(ARTICLE)]}),
        ("delta", {"text": "您好"}),
        ("delta", {"text": "。"}),
        ("done", {"finish_reason": "stop"}),
    ]
    assert not resources.upstream_slots.locked()
    schema = (await http.get("/openapi.json")).json()
    responses = schema["paths"][STREAM]["post"]["responses"]
    assert "text/event-stream" in responses["200"]["content"]
    assert "application/json" in responses["422"]["content"]


@pytest.mark.parametrize("path", [ANALYZE, STREAM])
async def test_invalid_request_is_json(harness, path):
    http, _, _, bearer, calls, _ = harness
    response = await http.post(path, headers=bearer(), json={"ticket_id": "not-a-uuid"})
    assert response.status_code == 422
    assert response.json()["error"] == "VALIDATION_ERROR"
    assert not calls


@pytest.mark.parametrize("partial", [False, True])
async def test_reply_retries_only_before_first_delta(harness, monkeypatch, partial):
    http, _, resources, bearer, _, _ = harness
    calls = 0

    async def pause(delay):
        assert not resources.upstream_slots.locked()

    async def stream(context):
        nonlocal calls
        calls += 1
        if partial or calls == 2:
            yield "hello"
        raise ProviderError(503, "LLM_UNAVAILABLE", "upstream error", retryable=True)

    monkeypatch.setattr(retry, "sleep", pause)
    monkeypatch.setattr(resources.provider, "stream_reply", stream)
    result = await http.post(STREAM, json={"ticket_id": str(TICKET)}, headers=bearer())
    assert calls == (1 if partial else 2)
    events = frames(result.text)
    assert [name for name, _ in events] == ["meta", "delta", "error"]
    assert events[-1][1] == {"code": 503, "error": "LLM_UNAVAILABLE", "detail": "upstream error", "retryable": True}
    assert not resources.upstream_slots.locked()


async def test_reply_emits_ping_and_terminates_at_total_deadline(harness, monkeypatch):
    http, application, resources, bearer, _, _ = harness
    settings = resources.settings.model_copy(update={"stream_timeout": 0.2, "stream_ping_interval": 0.01})
    application.state.resources = replace(resources, settings=settings)
    stopped = asyncio.Event()

    async def stream(context):
        try:
            yield "hello"
            await asyncio.Future()
        finally:
            stopped.set()

    monkeypatch.setattr(resources.provider, "stream_reply", stream)
    result = await http.post(STREAM, json={"ticket_id": str(TICKET)}, headers=bearer())
    events = frames(result.text)
    assert events[:2] == [("meta", events[0][1]), ("delta", {"text": "hello"})]
    assert events[2:-1] and all(event == ("ping", {}) for event in events[2:-1])
    assert events[-1] == ("error", {"code": 504, "error": "LLM_TIMEOUT", "detail": "模型生成超时", "retryable": False})
    assert stopped.is_set()
    assert not resources.upstream_slots.locked()


async def test_client_disconnect_closes_http_response_and_restores_capacity(harness):
    _, application, resources, bearer, _, _ = harness
    reading_more = asyncio.Event()
    upstream_closed = asyncio.Event()
    messages = []
    received_request = False

    class Upstream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'data: {"choices":[{"delta":{"content":"first"}}]}\n\n'
            reading_more.set()
            await asyncio.Future()

        async def aclose(self):
            upstream_closed.set()

    async def receive():
        nonlocal received_request
        if not received_request:
            received_request = True
            return {"type": "http.request", "body": json.dumps({"ticket_id": str(TICKET)}).encode(), "more_body": False}
        await reading_more.wait()
        assert resources.upstream_slots.locked()
        return {"type": "http.disconnect"}

    async def send(message):
        messages.append(message)

    headers = {**bearer(), "Content-Type": "application/json"}
    scope = {
        "type": "http",
        "asgi": {"spec_version": "2.4"},
        "method": "POST",
        "path": STREAM,
        "headers": [(key.lower().encode(), value.encode()) for key, value in headers.items()],
        "query_string": b"",
    }
    transport = httpx.MockTransport(lambda request: httpx.Response(200, stream=Upstream()))
    async with httpx.AsyncClient(transport=transport) as upstream:
        settings = resources.settings.model_copy(update={"llm_api_key": Settings().jwt_signing_key})
        provider = OpenAICompatibleProvider(settings, upstream)
        application.state.resources = replace(resources, provider=provider)
        async with asyncio.timeout(2):
            await application(scope, receive, send)

    assert upstream_closed.is_set()
    assert [message.get("body", b"").splitlines()[0] for message in messages if message.get("body")] == [
        b"event: meta",
        b"event: delta",
    ]
    await asyncio.wait_for(resources.upstream_slots.acquire(), timeout=1)
    assert resources.upstream_slots.locked()
    resources.upstream_slots.release()
