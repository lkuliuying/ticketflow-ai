import logging
from typing import Any, cast
from uuid import UUID

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.db.models import Q
from rest_framework_simplejwt.exceptions import TokenError

from common.core.auth.authentication import ServerAccessToken
from common.core.filter import get_filter_queryset
from common.core.permission import get_user_menu_queryset
from identity.services import UserInfo
from tickets.chat_services import CHAT_SEND_PERMISSION, chat_state, mark_chat_read
from tickets.models import Ticket
from tickets.notify import chat_group_name
from tickets.policy import TicketAccess, has_permission

logger = logging.getLogger(__name__)
CHAT_READ_PERMISSION = "chatMessages:TicketFlowTickets"


@database_sync_to_async
def _authorized_state(
    token: ServerAccessToken, user_id: int, ticket_id: UUID, *, mark_read: bool = False
) -> tuple[int, dict[str, Any]]:
    try:
        ServerAccessToken(token.token)
    except TokenError:
        return 4403, {}
    user = UserInfo.objects.filter(pk=user_id, is_active=True).first()
    if user is None:
        return 4403, {}
    if not user.is_superuser:
        menus = get_user_menu_queryset(user)
        menu_id = (
            menus.filter(name=CHAT_READ_PERMISSION, method="GET").values_list("pk", flat=True).first()
            if menus is not None
            else None
        )
        if menu_id is None:
            return 4403, {}
        cast(Any, user).menu = menu_id
    access = TicketAccess.for_user(user)
    scope = get_filter_queryset(access.scope(Ticket.objects.all()), user, fallback_q=Q())
    ticket = scope.filter(pk=ticket_id).first()
    if ticket is None:
        return 4404, {}
    if mark_read and has_permission(user, "chatRead:TicketFlowTickets"):
        mark_chat_read(ticket, user)
    return 0, chat_state(ticket, access, can_send=has_permission(user, CHAT_SEND_PERMISSION))


class TicketChatConsumer(AsyncJsonWebsocketConsumer):
    """工单实时排查会话 WebSocket 通道。"""

    ticket_id: UUID
    token: ServerAccessToken
    user_id: int
    group_name: str = ""
    closing: bool = False

    async def connect(self) -> None:
        user = self.scope.get("user")
        token = getattr(user, "auth", None)
        if not getattr(user, "is_authenticated", False) or not isinstance(token, ServerAccessToken):
            await self.close(code=4401)
            return
        self.token = token
        self.user_id = user.pk
        self.ticket_id = UUID(self.scope["url_route"]["kwargs"]["ticket_id"])
        close_code, state = await _authorized_state(self.token, self.user_id, self.ticket_id)
        if close_code:
            await self.close(code=close_code)
            return
        group_name = chat_group_name(self.ticket_id)
        await self.accept()
        try:
            await self.channel_layer.group_add(group_name, self.channel_name)
        except Exception:
            logger.warning("无法加入工单会话通道", exc_info=True)
            self.closing = True
            await self.close(code=1011)
            return
        self.group_name = group_name
        await self.send_json({"event": "chat.state", "data": state})

    async def disconnect(self, code: int) -> None:
        if self.group_name:
            try:
                await self.channel_layer.group_discard(self.group_name, self.channel_name)
            except Exception:
                # 此时连接已关闭，通道层会按组成员过期时间回收残留记录。
                logger.warning("无法退出工单会话通道", exc_info=True)

    async def _current_state(self, *, mark_read: bool = False) -> dict[str, Any] | None:
        if self.closing:
            return None
        close_code, state = await _authorized_state(self.token, self.user_id, self.ticket_id, mark_read=mark_read)
        if close_code:
            self.closing = True
            await self.close(code=4403)
            return None
        return state

    async def receive_json(self, content: Any, **kwargs: Any) -> None:
        if not isinstance(content, dict):
            return
        action = content.get("action")
        if action == "ping":
            if await self._current_state() is not None:
                await self.send_json({"event": "pong"})
        elif action == "mark_read":
            await self._current_state(mark_read=True)

    async def chat_message(self, event: dict[str, Any]) -> None:
        if await self._current_state() is not None:
            await self.send_json({"event": "chat.message", "data": event["payload"]})

    async def chat_state(self, event: dict[str, Any]) -> None:
        state = await self._current_state()
        if state is not None:
            await self.send_json({"event": "chat.state", "data": state})
