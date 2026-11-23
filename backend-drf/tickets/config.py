from django.urls import include, path, re_path

from tickets.rating_views import TicketRatingViewSet
from tickets.urls import ratings_urlpatterns
from tickets.views import TicketViewSet

URLPATTERNS = [
    re_path(r"^api/tickets$", TicketViewSet.as_view({"get": "list", "post": "create"}), name="ticket-list"),
    path("api/tickets/", include("tickets.urls")),
    re_path(r"^api/ticket-ratings$", TicketRatingViewSet.as_view({"get": "list"}), name="ticket-rating-list"),
    re_path(r"^api/ticket-ratings/", include(ratings_urlpatterns)),
]
PERMISSION_WHITE_REURL: dict[str, list[str]] = {}
