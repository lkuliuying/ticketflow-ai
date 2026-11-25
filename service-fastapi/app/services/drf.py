from asyncio import sleep, timeout
from http import HTTPStatus
from random import uniform
from typing import Literal
from uuid import UUID

import httpx

from app.core.errors import ServiceError
from app.core.request_id import get_request_id
from app.core.resources import Resources
from app.schemas.assistant import AnswerInput, AnswerResult, AssistantContext, ChatRequest, QuestionContext
from app.schemas.context import DrfResponse, TicketContext

FORWARDED_ERRORS = {
    401: ("UNAUTHORIZED", "用户凭证无效"),
    403: ("FORBIDDEN", "无权使用此工单的 AI 上下文"),
    404: ("NOT_FOUND", "工单不存在"),
    429: ("RATE_LIMITED", "DRF 请求过于频繁"),
}
ASSISTANT_ERRORS = {
    **FORWARDED_ERRORS,
    400: ("VALIDATION_ERROR", "会话请求无效"),
    403: ("FORBIDDEN", "无权使用 AI 助手"),
    404: ("NOT_FOUND", "会话或问题不存在"),
    409: ("CONFLICT", "会话状态冲突"),
}


def _request_headers(resources: Resources, raw_token: str, *, user_id: str | int | None = None) -> dict[str, str]:
    headers: dict[str, str] = {}
    secret = resources.settings.internal_api_secret
    if secret is not None and secret.get_secret_value().strip():
        headers["X-Internal-Token"] = secret.get_secret_value()
        if user_id is not None:
            headers["X-Internal-User-Id"] = str(user_id)
    if "X-Internal-User-Id" not in headers:
        headers["Authorization"] = f"Bearer {raw_token}"
    request_id = get_request_id()
    if request_id:
        headers["X-Request-ID"] = request_id
    return headers


async def _request_with_retries(
    resources: Resources,
    url: str,
    headers: dict[str, str],
    method: Literal["GET", "POST"],
    payload: dict[str, object] | None,
    retries_left: int,
) -> httpx.Response:
    backoff = 0.1
    while True:
        try:
            response = await resources.drf_http.request(method, url, headers=headers, json=payload)
        except httpx.ConnectError, httpx.ConnectTimeout:
            if not retries_left:
                raise
        else:
            if response.status_code < 500 or not retries_left:
                return response
        await sleep(uniform(0, backoff))
        backoff *= 2
        retries_left -= 1


def _drf_error(response: httpx.Response, errors: dict[int, tuple[str, str]]) -> ServiceError:
    status = response.status_code
    if status not in errors:
        return ServiceError(503, "DRF_UNAVAILABLE", "DRF 上下文服务不可用")

    error, detail = errors[status]
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


async def _request(
    resources: Resources,
    path: str,
    raw_token: str,
    *,
    method: Literal["GET", "POST"] = "GET",
    payload: dict[str, object] | None = None,
    success: HTTPStatus = HTTPStatus.OK,
    retry: bool = True,
    errors: dict[int, tuple[str, str]] = FORWARDED_ERRORS,
    user_id: str | int | None = None,
) -> httpx.Response:
    base_url = str(resources.settings.drf_base_url).rstrip("/")
    retries = resources.settings.drf_max_retries if retry else 0
    headers = _request_headers(resources, raw_token, user_id=user_id)
    try:
        async with timeout(resources.settings.drf_total_timeout):
            response = await _request_with_retries(resources, f"{base_url}{path}", headers, method, payload, retries)
    except httpx.PoolTimeout as exc:
        raise ServiceError(503, "UPSTREAM_BUSY", "DRF 上下文连接池已用完") from exc
    except (httpx.TimeoutException, TimeoutError) as exc:
        raise ServiceError(504, "DRF_TIMEOUT", "DRF 上下文请求超时") from exc
    except httpx.RequestError as exc:
        raise ServiceError(503, "DRF_UNAVAILABLE", "DRF 上下文服务不可用") from exc

    if response.status_code != success:
        raise _drf_error(response, errors)
    return response


def _decode[T](response: httpx.Response, schema: type[DrfResponse[T]], detail: str) -> T:
    try:
        return schema.model_validate_json(response.content).data
    except ValueError as exc:
        raise ServiceError(503, "DRF_INVALID_CONTEXT", detail) from exc


async def fetch_ticket_context(
    resources: Resources, ticket_id: UUID, raw_token: str, *, purpose: str | None = None
) -> TicketContext:
    path = f"/api/tickets/{ticket_id}/ai-context"
    if purpose:
        path = f"{path}?purpose={purpose}"
    response = await _request(resources, path, raw_token)
    context = _decode(response, DrfResponse[TicketContext], "DRF 返回了无效的工单上下文")
    if context.ticket.id != ticket_id:
        raise ServiceError(503, "DRF_INVALID_CONTEXT", "DRF 返回了无效的工单上下文")
    return context


async def record_question(resources: Resources, body: ChatRequest, raw_token: str) -> QuestionContext:
    response = await _request(
        resources,
        f"/api/assistant/internal/sessions/{body.session_id}/question",
        raw_token,
        method="POST",
        payload={"message": body.message},
        success=HTTPStatus.CREATED,
        retry=False,
        errors=ASSISTANT_ERRORS,
    )
    return _decode(response, DrfResponse[QuestionContext], "DRF 返回了无效的提问上下文")


async def record_answer(
    resources: Resources,
    session_id: UUID,
    body: AnswerInput,
    raw_token: str,
    *,
    user_id: str | int | None = None,
) -> AnswerResult:
    response = await _request(
        resources,
        f"/api/assistant/internal/sessions/{session_id}/answer",
        raw_token,
        method="POST",
        payload=body.model_dump(mode="json"),
        errors=ASSISTANT_ERRORS,
        user_id=user_id,
    )
    return _decode(response, DrfResponse[AnswerResult], "DRF 返回了无效的回答标识")


async def fetch_assistant_context(resources: Resources, session_id: UUID, raw_token: str) -> AssistantContext:
    response = await _request(
        resources, f"/api/assistant/internal/sessions/{session_id}/context", raw_token, errors=ASSISTANT_ERRORS
    )
    return _decode(response, DrfResponse[AssistantContext], "DRF 返回了无效的会话上下文")
