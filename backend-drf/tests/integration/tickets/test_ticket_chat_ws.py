from hashlib import md5
from unittest.mock import AsyncMock, patch

import pytest
from asgiref.sync import async_to_sync
from channels.db import database_sync_to_async
from channels.layers import get_channel_layer
from channels.testing import WebsocketCommunicator
from rest_framework_simplejwt.tokens import RefreshToken

from common.cache.storage import BlackAccessTokenCache
from identity.models import UserInfo
from server.asgi import application
from system.models import Menu
from tickets.models import Status
from tickets.notify import chat_group_name

pytestmark = pytest.mark.django_db


def _communicator(ticket_id, token=None) -> WebsocketCommunicator:
    headers = [(b"origin", b"http://testserver"), (b"host", b"testserver")]
    if token is not None:
        headers.append((b"cookie", f"X-Token={token}".encode()))
    return WebsocketCommunicator(application, f"/ws/tickets/{ticket_id}/chat/", headers=headers)


def test_ticket_chat_ws_auth_and_broadcast(users, make_ticket, settings):
    settings.CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}
    ticket = make_ticket(status=Status.IN_PROGRESS, assignee=users["agent"])
    outsider_user = UserInfo.objects.create_user(username="ws-outsider")
    outsider_user.roles.set(users["requester"].roles.all())
    outsider_token = str(RefreshToken.for_user(outsider_user).access_token)
    requester_token = str(RefreshToken.for_user(users["requester"]).access_token)

    async def scenario():
        anon = _communicator(ticket.pk)
        connected, close_code = await anon.connect()
        assert not connected
        assert close_code == 4401

        outsider = _communicator(ticket.pk, outsider_token)
        connected, close_code = await outsider.connect()
        assert not connected
        assert close_code == 4404

        comm = _communicator(ticket.pk, requester_token)
        connected, _ = await comm.connect()
        assert connected
        initial = await comm.receive_json_from()
        assert initial == {"event": "chat.state", "data": {"can_send": True, "lock_reason": ""}}

        await comm.send_json_to([])
        await comm.send_to(text_data="null")
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


@pytest.mark.parametrize("revocation", ["inactive", "role", "menu", "scope", "logout"])
def test_chat_closes_without_delivering_after_access_loss(users, make_ticket, settings, revocation):
    settings.CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}
    agent = users["agent"]
    ticket = make_ticket(status=Status.IN_PROGRESS, assignee=agent)
    token = str(RefreshToken.for_user(agent).access_token)
    blacklist = BlackAccessTokenCache(agent.pk, md5(token.encode(), usedforsecurity=False).hexdigest())

    @database_sync_to_async
    def revoke():
        if revocation == "inactive":
            UserInfo.objects.filter(pk=agent.pk).update(is_active=False)
        elif revocation == "role":
            agent.roles.clear()
        elif revocation == "menu":
            agent.roles.get().menu.remove(Menu.objects.get(name="chatMessages:TicketFlowTickets"))
        elif revocation == "scope":
            ticket.assignee = None
            ticket.save(update_fields=["assignee"])
        else:
            blacklist.set_storage_cache(True)

    async def scenario():
        comm = _communicator(ticket.pk, token)
        assert (await comm.connect())[0]
        assert (await comm.receive_json_from())["event"] == "chat.state"
        await revoke()
        await get_channel_layer().group_send(chat_group_name(ticket.pk), {"type": "chat.message", "payload": {}})
        frame = await comm.receive_output()
        assert frame == {"type": "websocket.close", "code": 4403}
        await comm.disconnect()

    try:
        async_to_sync(scenario)()
    finally:
        if revocation == "logout":
            blacklist.del_storage_cache()


@pytest.mark.parametrize("join_fails", [True, False], ids=["group-add", "group-discard"])
def test_chat_handles_unavailable_channel_layer(users, make_ticket, settings, join_fails):
    settings.CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}
    ticket = make_ticket(status=Status.IN_PROGRESS, assignee=users["agent"])
    user = users["requester"]
    token = str(RefreshToken.for_user(user).access_token)

    async def scenario():
        comm = _communicator(ticket.pk, token)
        layer = get_channel_layer()
        error = ConnectionError("channel layer unavailable")
        add = AsyncMock(wraps=layer.group_add, side_effect=error if join_fails else None)
        discard = AsyncMock(side_effect=error)
        with patch.object(layer, "group_add", add), patch.object(layer, "group_discard", discard):
            connected, _ = await comm.connect()
            assert connected
            if join_fails:
                assert await comm.receive_output() == {"type": "websocket.close", "code": 1011}
            else:
                assert (await comm.receive_json_from())["event"] == "chat.state"
            await comm.disconnect()
        add.assert_awaited_once()
        if join_fails:
            discard.assert_not_awaited()
        else:
            discard.assert_awaited_once()

    async_to_sync(scenario)()
