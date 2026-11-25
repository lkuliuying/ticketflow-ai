from contextvars import ContextVar
from uuid import uuid4

from starlette.types import ASGIApp, Message, Receive, Scope, Send

REQUEST_ID_HEADER = b"x-request-id"
_request_id_var: ContextVar[str] = ContextVar("ticketflow_request_id", default="")


def get_request_id() -> str:
    return _request_id_var.get()


class RequestIdMiddleware:
    """Pure ASGI middleware that propagates X-Request-ID without buffering SSE."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = ""
        for key, value in scope.get("headers", ()):
            if key.lower() == REQUEST_ID_HEADER:
                incoming = value.decode("latin1").strip()
                break
        request_id = incoming[:128] if incoming else uuid4().hex
        token = _request_id_var.set(request_id)

        async def send_with_request_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", ()))
                headers = [(k, v) for k, v in headers if k.lower() != REQUEST_ID_HEADER]
                headers.append((REQUEST_ID_HEADER, request_id.encode("latin1")))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            _request_id_var.reset(token)
