import hmac
from typing import Any

from django.conf import settings
from django.contrib.auth import get_user_model
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import PermissionDenied
from rest_framework.request import Request

INTERNAL_TOKEN_HEADER = "X-Internal-Token"
INTERNAL_USER_HEADER = "X-Internal-User-Id"


def configured_internal_secret() -> str:
    return str(getattr(settings, "TICKETFLOW_INTERNAL_API_SECRET", "") or "").strip()


def has_valid_internal_token(request: Request) -> bool:
    expected = configured_internal_secret()
    if not expected:
        return False
    provided = str(request.headers.get(INTERNAL_TOKEN_HEADER, "") or "").strip()
    return bool(provided) and hmac.compare_digest(provided, expected)


def verify_internal_request(request: Request) -> None:
    """Enforce the shared internal service secret when configured."""
    if not configured_internal_secret():
        return
    if not has_valid_internal_token(request):
        raise PermissionDenied("缺少有效的内部服务凭证")


class InternalServiceUserAuthentication(BaseAuthentication):
    """Authenticate internal callbacks with the shared secret and explicit user ID."""

    def authenticate_header(self, request: Request) -> str:
        return "Bearer"

    def authenticate(self, request: Request) -> tuple[Any, dict[str, Any]] | None:
        if not has_valid_internal_token(request):
            return None
        raw_user_id = str(request.headers.get(INTERNAL_USER_HEADER, "") or "").strip()
        if not raw_user_id or not raw_user_id.isdigit():
            return None
        user_model = get_user_model()
        user = user_model.objects.filter(pk=int(raw_user_id), is_active=True).first()
        if user is None:
            return None
        return user, {"internal_service": True}
