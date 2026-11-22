from asyncio import Semaphore
from contextlib import asynccontextmanager
from uuid import UUID

import httpx
import pytest
from anyio import sleep_forever
from redis.asyncio import Redis

from app.core.config import Settings
from app.core.errors import ServiceError
from app.core.resources import Resources
from app.services import drf

TICKET = UUID("2da1c8a8-31ca-40d4-90e3-e3842c849b02")
ARTICLE = UUID("895ae0b4-b253-47de-80bd-6a4cd642f8eb")
PATH = f"/api/tickets/{TICKET}/ai-context"
TOKEN = "original-access-token"
pytestmark = pytest.mark.anyio


@pytest.fixture
def context_response():
    return {
        "code": 1000,
        "data": {
            "ticket": {
                "id": str(TICKET),
                "title": "VPN 无法连接",
                "description": "连接时客户端提示超时",
                "category": "NETWORK",
                "priority": "P1",
                "version": 2,
            },
            "categories": ["ACCOUNT", "NETWORK"],
            "references": [{"article_id": str(ARTICLE), "title": "VPN 排障", "excerpt": "检查入口地址"}],
        },
    }


@asynccontextmanager
async def transport_resources(transport, **overrides):
    settings = Settings(drf_base_url="http://drf:8896", **overrides)
    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as http, Redis() as redis:
        yield Resources(settings, http, redis, Semaphore(1))


async def test_context_forwards_original_bearer_and_parses_drf_envelope(context_response):
    def transport(request):
        assert request.method == "GET"
        assert request.url == f"http://drf:8896{PATH}"
        assert request.headers["Authorization"] == f"Bearer {TOKEN}"
        return httpx.Response(200, json=context_response)

    async with transport_resources(transport) as resources:
        context = await drf.fetch_ticket_context(resources, TICKET, TOKEN)

    assert context.ticket.id == TICKET
    assert context.ticket.version == 2
    assert context.ticket.priority == "P1"
    assert context.categories == ["ACCOUNT", "NETWORK"]
    assert context.references[0].article_id == ARTICLE
    assert context.model_dump(mode="json") == context_response["data"]


@pytest.mark.parametrize(
    ("status", "code", "headers"),
    [
        (401, "UNAUTHORIZED", {"WWW-Authenticate": "Bearer"}),
        (403, "FORBIDDEN", {}),
        (404, "NOT_FOUND", {}),
        (429, "RATE_LIMITED", {"Retry-After": "17"}),
    ],
)
async def test_drf_errors_are_not_retried(status, code, headers):
    calls = []

    def transport(request):
        calls.append(request)
        return httpx.Response(status, headers={"Retry-After": "17"}, json={"code": 2000, "detail": "工单授权错误"})

    async with transport_resources(transport) as resources:
        with pytest.raises(ServiceError) as raised:
            await drf.fetch_ticket_context(resources, TICKET, TOKEN)

    assert (raised.value.status_code, raised.value.code, raised.value.detail) == (status, code, "工单授权错误")
    assert raised.value.headers == headers
    assert len(calls) == 1


async def test_drf_retries_connections_and_5xx_with_slot_released(monkeypatch, context_response):
    calls = []
    bounds = []

    def transport(request):
        calls.append(request)
        if len(calls) == 1:
            raise httpx.ConnectError("connection dropped", request=request)
        if len(calls) == 2:
            return httpx.Response(502)
        return httpx.Response(200, json=context_response)

    def jitter(low, high):
        bounds.append((low, high))
        return high / 2

    async def pause(delay):
        assert not resources.upstream_slots.locked()
        delays.append(delay)

    delays = []
    monkeypatch.setattr(drf, "uniform", jitter)
    monkeypatch.setattr(drf, "sleep", pause)
    async with transport_resources(transport) as resources:
        assert (await drf.fetch_ticket_context(resources, TICKET, TOKEN)).ticket.id == TICKET

    assert len(calls) == 3
    assert bounds == [(0, 0.1), (0, 0.2)]
    assert delays == [0.05, 0.1]


@pytest.mark.parametrize(
    ("failure", "attempts", "status", "code"),
    [
        (503, 3, 503, "DRF_UNAVAILABLE"),
        (httpx.ConnectError, 3, 503, "DRF_UNAVAILABLE"),
        (httpx.ConnectTimeout, 3, 504, "DRF_TIMEOUT"),
        (httpx.ReadTimeout, 1, 504, "DRF_TIMEOUT"),
        (httpx.WriteError, 1, 503, "DRF_UNAVAILABLE"),
    ],
)
async def test_drf_exhaustion_and_timeout_mapping(monkeypatch, failure, attempts, status, code):
    calls = []

    def transport(request):
        calls.append(request)
        if isinstance(failure, int):
            return httpx.Response(failure, text="private upstream failure")
        raise failure("private upstream failure", request=request)

    monkeypatch.setattr(drf, "uniform", lambda low, high: 0)
    async with transport_resources(transport) as resources:
        with pytest.raises(ServiceError) as raised:
            await drf.fetch_ticket_context(resources, TICKET, TOKEN)

    assert (raised.value.status_code, raised.value.code) == (status, code)
    assert "private upstream failure" not in raised.value.detail
    assert len(calls) == attempts


async def test_total_budget_cancels_request_and_releases_slot():
    async def transport(request):
        await sleep_forever()

    async with transport_resources(transport, drf_total_timeout=0.02) as resources:
        with pytest.raises(ServiceError) as raised:
            await drf.fetch_ticket_context(resources, TICKET, TOKEN)
        assert not resources.upstream_slots.locked()

    assert (raised.value.status_code, raised.value.code) == (504, "DRF_TIMEOUT")


async def test_wait_for_slot_has_its_own_budget():
    def transport(request):
        pytest.fail("must not make an HTTP request without a slot")

    async with transport_resources(transport, upstream_slot_timeout=0.02) as resources:
        async with resources.upstream_slots:
            with pytest.raises(ServiceError) as raised:
                await drf.fetch_ticket_context(resources, TICKET, TOKEN)

    assert (raised.value.status_code, raised.value.code) == (503, "UPSTREAM_BUSY")


@pytest.mark.parametrize("invalid", ["envelope", "wrong_ticket", "missing_reference_field", "not_json"])
async def test_malformed_drf_context_is_rejected(context_response, invalid):
    def transport(request):
        if invalid == "not_json":
            return httpx.Response(200, text="not a JSON document")
        if invalid == "envelope":
            context_response["code"] = 2000
        if invalid == "wrong_ticket":
            context_response["data"]["ticket"]["id"] = str(ARTICLE)
        if invalid == "missing_reference_field":
            del context_response["data"]["references"][0]["excerpt"]
        return httpx.Response(200, json=context_response)

    async with transport_resources(transport) as resources:
        with pytest.raises(ServiceError) as raised:
            await drf.fetch_ticket_context(resources, TICKET, TOKEN)

    assert (raised.value.status_code, raised.value.code) == (503, "DRF_INVALID_CONTEXT")
