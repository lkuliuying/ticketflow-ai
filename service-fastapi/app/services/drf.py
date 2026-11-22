from asyncio import sleep, timeout
from http import HTTPStatus
from random import uniform
from uuid import UUID

import httpx

from app.core.errors import ServiceError
from app.core.resources import Resources
from app.schemas.context import DrfContextResponse, TicketContext

FORWARDED_ERRORS = {
    401: ("UNAUTHORIZED", "用户凭证无效"),
    403: ("FORBIDDEN", "无权使用此工单的 AI 上下文"),
    404: ("NOT_FOUND", "工单不存在"),
    429: ("RATE_LIMITED", "DRF 请求过于频繁"),
}


async def _request_with_retries(resources: Resources, url: str, raw_token: str) -> httpx.Response:
    headers = {"Authorization": f"Bearer {raw_token}"}
    retries_left = resources.settings.drf_max_retries
    backoff = 0.1
    while True:
        try:
            response = await resources.drf_http.get(url, headers=headers)
        except httpx.ConnectError, httpx.ConnectTimeout:
            if not retries_left:
                raise
        else:
            if response.status_code < 500 or not retries_left:
                return response
        await sleep(uniform(0, backoff))
        backoff *= 2
        retries_left -= 1


def _drf_error(response: httpx.Response) -> ServiceError:
    status = response.status_code
    if status not in FORWARDED_ERRORS:
        return ServiceError(503, "DRF_UNAVAILABLE", "DRF 上下文服务不可用")

    error, detail = FORWARDED_ERRORS[status]
    try:
        payload = response.json()
    except ValueError:
        payload = None
    if isinstance(payload, dict) and isinstance(payload.get("detail"), str) and payload["detail"]:
        detail = payload["detail"]
    headers = {}
    if status == 401:
        headers["WWW-Authenticate"] = "Bearer"
    if status == 429 and "Retry-After" in response.headers:
        headers["Retry-After"] = response.headers["Retry-After"]
    return ServiceError(status, error, detail, headers)


async def fetch_ticket_context(resources: Resources, ticket_id: UUID, raw_token: str) -> TicketContext:
    base_url = str(resources.settings.drf_base_url).rstrip("/")
    url = f"{base_url}/api/tickets/{ticket_id}/ai-context"
    try:
        async with timeout(resources.settings.drf_total_timeout):
            response = await _request_with_retries(resources, url, raw_token)
    except httpx.PoolTimeout as exc:
        raise ServiceError(503, "UPSTREAM_BUSY", "DRF 上下文连接池已用完") from exc
    except (httpx.TimeoutException, TimeoutError) as exc:
        raise ServiceError(504, "DRF_TIMEOUT", "DRF 上下文请求超时") from exc
    except httpx.RequestError as exc:
        raise ServiceError(503, "DRF_UNAVAILABLE", "DRF 上下文服务不可用") from exc

    if response.status_code != HTTPStatus.OK:
        raise _drf_error(response)
    try:
        context = DrfContextResponse.model_validate_json(response.content).data
    except ValueError as exc:
        raise ServiceError(503, "DRF_INVALID_CONTEXT", "DRF 返回了无效的工单上下文") from exc
    if context.ticket.id != ticket_id:
        raise ServiceError(503, "DRF_INVALID_CONTEXT", "DRF 返回了无效的工单上下文")
    return context
