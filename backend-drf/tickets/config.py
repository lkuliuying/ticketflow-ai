from django.urls import include, path, re_path

from tickets.views import TicketViewSet

URLPATTERNS = [
    re_path(r"^api/tickets$", TicketViewSet.as_view({"get": "list", "post": "create"}), name="ticket-list"),
    path("api/tickets/", include("tickets.urls")),
]
PERMISSION_WHITE_REURL: dict[str, list[str]] = {}
