import logging
from collections.abc import Iterable
from typing import Any
from uuid import UUID

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.contrib.auth import get_user_model

from notifications.services import BACKEND, UserMessage

logger = logging.getLogger(__name__)


def chat_group_name(ticket_id: UUID | str) -> str:
    return f"ticketflow_chat_{ticket_id}"


def broadcast_chat_event(ticket_id: UUID | str, event: str, payload: dict[str, Any]) -> None:
    """Broadcast a ticket chat event to all connected WebSocket clients in the ticket room."""
    layer = get_channel_layer()
    if layer is None:
        return
    try:
        async_to_sync(layer.group_send)(chat_group_name(ticket_id), {"type": event, "payload": payload})
    except Exception:
        logger.warning("工单会话广播失败 ticket_id=%s event=%s", ticket_id, event, exc_info=True)


class TicketSiteMessage(UserMessage):
    category = "ticketflow"
    category_label = "工单系统"
    message_type_label = "工单动态"

    def __init__(self, user: Any, subject: str, body: str) -> None:
        super().__init__(user)
        self._subject = subject
        self._body = body

    def get_html_msg(self) -> dict[str, Any]:
        return {"subject": self._subject, "message": self._body}


def notify_users(user_ids: Iterable[int | None], subject: str, body: str) -> None:
    """Send site-message notifications to active users without failing the caller."""
    unique_ids = list(dict.fromkeys(uid for uid in user_ids if uid is not None))
    if not unique_ids:
        return
    user_model = get_user_model()
    users = list(user_model.objects.filter(pk__in=unique_ids, is_active=True))
    for user in users:
        try:
            msg = TicketSiteMessage(user, subject, body)
            mapper = msg.get_backend_msg_mapper([BACKEND.SITE_MSG])
            msg.send_msg([user.pk], mapper)
        except Exception:
            logger.warning("工单站内通知发送失败 user_id=%s", user.pk, exc_info=True)
