import pytest
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from channels.testing import WebsocketCommunicator
from django.contrib.auth.models import AnonymousUser

from identity.models import UserInfo
from tickets.consumers import TicketChatConsumer
from tickets.models import Status
from tickets.notify import chat_group_name

pytestmark = pytest.mark.django_db


def _communicator(user, ticket_id: str) -> WebsocketCommunicator:
    app = TicketChatConsumer.as_asgi()
    comm = WebsocketCommunicator(app, f"/ws/tickets/{ticket_id}/chat/")
    comm.scope["user"] = user
    comm.scope["url_route"] = {"kwargs": {"ticket_id": ticket_id}}
    return comm


def test_ticket_chat_ws_auth_and_broadcast(users, make_ticket, settings):
    settings.CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}
    ticket = make_ticket(status=Status.IN_PROGRESS, assignee=users["agent"])
    outsider_user = UserInfo.objects.create_user(username="ws-outsider")

    async def scenario():
        anon = _communicator(AnonymousUser(), str(ticket.pk))
        connected, close_code = await anon.connect()
        assert not connected
        assert close_code == 4401

        outsider = _communicator(outsider_user, str(ticket.pk))
        connected, close_code = await outsider.connect()
        assert not connected
        assert close_code == 4404

        comm = _communicator(users["requester"], str(ticket.pk))
        connected, _ = await comm.connect()
        assert connected
        initial = await comm.receive_json_from()
        assert initial == {"event": "chat.state", "data": {"can_send": True, "lock_reason": ""}}

        await comm.send_json_to({"action": "ping"})
        assert await comm.receive_json_from() == {"event": "pong"}

        layer = get_channel_layer()
        await layer.group_send(
            chat_group_name(ticket.pk),
            {"type": "chat.message", "payload": {"id": "m1", "kind": "TEXT", "content": "实时推送"}},
        )
        pushed = await comm.receive_json_from()
        assert pushed == {"event": "chat.message", "data": {"id": "m1", "kind": "TEXT", "content": "实时推送"}}

        await comm.disconnect()

    async_to_sync(scenario)()
