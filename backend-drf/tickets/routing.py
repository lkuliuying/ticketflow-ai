from django.urls import re_path

from tickets.consumers import TicketChatConsumer

urlpatterns = [
    re_path(
        r"ws/tickets/(?P<ticket_id>[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/chat/$",
        TicketChatConsumer.as_asgi(),
    ),
]
