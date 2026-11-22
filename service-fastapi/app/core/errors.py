from collections.abc import Mapping
from http import HTTPStatus

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.schemas.http import ErrorResponse


class ServiceError(HTTPException):
    def __init__(self, status_code: int, code: str, detail: str, headers: dict[str, str] | None = None) -> None:
        super().__init__(status_code, detail, headers)
        self.code = code


class AuthRedisUnavailable(ServiceError):
    def __init__(self) -> None:
        super().__init__(503, "AUTH_REDIS_UNAVAILABLE", "认证 Redis 不可用")


def error_response(status_code: int, code: str, detail: str, headers: Mapping[str, str] | None = None) -> JSONResponse:
    payload = ErrorResponse(code=code, detail=detail)
    return JSONResponse(payload.model_dump(), status_code=status_code, headers=headers)


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        status = HTTPStatus(exc.status_code)
        code = exc.code if isinstance(exc, ServiceError) else status.name
        detail = exc.detail if isinstance(exc.detail, str) else status.phrase
        return error_response(status, code, detail, exc.headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        details = [f"{'.'.join(map(str, error['loc']))}: {error['msg']}" for error in exc.errors()]
        return error_response(422, "VALIDATION_ERROR", "; ".join(details))

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        return error_response(500, "INTERNAL_SERVER_ERROR", "服务内部错误")
