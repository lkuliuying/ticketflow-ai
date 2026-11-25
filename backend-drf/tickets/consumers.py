from typing import Any
from uuid import UUID

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

from tickets.chat_services import chat_state, mark_chat_read
from tickets.models import Ticket
from tickets.notify import chat_group_name
from tickets.policy import TicketAccess


@database_sync_to_async
def _load_ticket_state(user: Any, ticket_id: str) -> dict[str, Any] | None:
    try:
        parsed_id = UUID(ticket_id)
    except ValueError:
        return None
    access = TicketAccess.for_user(user)
    ticket = access.scope(Ticket.objects.all()).filter(pk=parsed_id).first()
    if ticket is None:
        return None
    return chat_state(ticket, access)


@database_sync_to_async
def _mark_read(user: Any, ticket_id: str) -> None:
    try:
        parsed_id = UUID(ticket_id)
    except ValueError:
        return
    access = TicketAccess.for_user(user)
    ticket = access.scope(Ticket.objects.all()).filter(pk=parsed_id).first()
    if ticket is not None:
        mark_chat_read(ticket, user)


class TicketChatConsumer(AsyncJsonWebsocketConsumer):
    """工单实时排查会话 WebSocket 通道。"""

    ticket_id: str = ""
    group_name: str = ""

    async def connect(self) -> None:
        user = self.scope.get("user")
        if user is None or not getattr(user, "is_authenticated", False):
            await self.close(code=4401)
            return
        self.ticket_id = str(self.scope["url_route"]["kwargs"].get("ticket_id", ""))
        state = await _load_ticket_state(user, self.ticket_id)
        if state is None:
            await self.close(code=4404)
            return
        self.group_name = chat_group_name(self.ticket_id)
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()
        await self.send_json({"event": "chat.state", "data": state})

    async def disconnect(self, code: int) -> None:
        if self.group_name:
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive_json(self, content: dict[str, Any], **kwargs: Any) -> None:
        action = str(content.get("action", "") or "").strip()
        if action == "ping":
            await self.send_json({"event": "pong"})
        elif action == "mark_read":
            user = self.scope.get("user")
            if user is not None and getattr(user, "is_authenticated", False):
                await _mark_read(user, self.ticket_id)

    async def chat_message(self, event: dict[str, Any]) -> None:
        await self.send_json({"event": "chat.message", "data": event["payload"]})

    async def chat_state(self, event: dict[str, Any]) -> None:
        user = self.scope.get("user")
        if user is None or not getattr(user, "is_authenticated", False):
            return
        state = await _load_ticket_state(user, self.ticket_id)
        if state is None:
            await self.close(code=4403)
            return
        await self.send_json({"event": "chat.state", "data": state})
