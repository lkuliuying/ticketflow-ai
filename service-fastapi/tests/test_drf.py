from asyncio import Semaphore
from contextlib import asynccontextmanager

import httpx
import pytest
from anyio import sleep_forever
from conftest import ARTICLE, TICKET
from redis.asyncio import Redis

from app.core.config import Settings
from app.core.errors import ServiceError
from app.core.resources import Resources
from app.services import drf
from app.services.providers import MockProvider

PATH = f"/api/tickets/{TICKET}/ai-context"
TOKEN = "original-access-token"
pytestmark = pytest.mark.anyio


@asynccontextmanager
async def transport_resources(transport, **overrides):
    settings = Settings(drf_base_url="http://drf:8896", **overrides)
    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as http, Redis() as redis:
        yield Resources(settings, http, redis, Semaphore(1), MockProvider(settings))


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
    ("status", "error", "headers"),
    [
        (401, "UNAUTHORIZED", {"WWW-Authenticate": "Bearer"}),
        (403, "FORBIDDEN", {}),
        (404, "NOT_FOUND", {}),
        (429, "RATE_LIMITED", {"Retry-After": "17"}),
    ],
)
async def test_drf_errors_are_not_retried(status, error, headers):
    calls = []

    def transport(request):
        calls.append(request)
        return httpx.Response(status, headers={"Retry-After": "17"}, json={"code": 2000, "detail": "工单授权错误"})

    async with transport_resources(transport) as resources:
        with pytest.raises(ServiceError) as raised:
            await drf.fetch_ticket_context(resources, TICKET, TOKEN)

    assert (raised.value.status_code, raised.value.error, raised.value.detail) == (status, error, "工单授权错误")
    assert raised.value.headers == headers
    assert len(calls) == 1


async def test_drf_retries_connections_and_5xx_with_jitter(monkeypatch, context_response):
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
    ("failure", "attempts", "status", "error"),
    [
        (503, 3, 503, "DRF_UNAVAILABLE"),
        (httpx.ConnectError, 3, 503, "DRF_UNAVAILABLE"),
        (httpx.ConnectTimeout, 3, 504, "DRF_TIMEOUT"),
        (httpx.ReadTimeout, 1, 504, "DRF_TIMEOUT"),
        (httpx.PoolTimeout, 1, 503, "UPSTREAM_BUSY"),
        (httpx.WriteError, 1, 503, "DRF_UNAVAILABLE"),
    ],
)
async def test_drf_exhaustion_and_timeout_mapping(monkeypatch, failure, attempts, status, error):
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

    assert (raised.value.status_code, raised.value.error) == (status, error)
    assert "private upstream failure" not in raised.value.detail
    assert len(calls) == attempts


async def test_total_budget_cancels_request():
    cancelled = False

    async def transport(request):
        nonlocal cancelled
        try:
            await sleep_forever()
        finally:
            cancelled = True

    async with transport_resources(transport, drf_total_timeout=0.02) as resources:
        with pytest.raises(ServiceError) as raised:
            await drf.fetch_ticket_context(resources, TICKET, TOKEN)

    assert cancelled
    assert (raised.value.status_code, raised.value.error) == (504, "DRF_TIMEOUT")


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

    assert (raised.value.status_code, raised.value.error) == (503, "DRF_INVALID_CONTEXT")
