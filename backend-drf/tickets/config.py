from django.urls import include, path, re_path

from tickets.management_views import AccountViewSet, SkillGroupViewSet
from tickets.rating_views import TicketRatingViewSet
from tickets.urls import account_urlpatterns, ratings_urlpatterns, skill_group_urlpatterns
from tickets.views import TicketViewSet

URLPATTERNS = [
    re_path(r"^api/tickets$", TicketViewSet.as_view({"get": "list", "post": "create"}), name="ticket-list"),
    path("api/tickets/", include("tickets.urls")),
    re_path(r"^api/ticket-ratings$", TicketRatingViewSet.as_view({"get": "list"}), name="ticket-rating-list"),
    re_path(r"^api/ticket-ratings/", include(ratings_urlpatterns)),
    re_path(
        r"^api/ticketflow/accounts$",
        AccountViewSet.as_view({"get": "list", "post": "create"}),
        name="ticketflow-account-list",
    ),
    re_path(r"^api/ticketflow/accounts/", include(account_urlpatterns)),
    re_path(
        r"^api/ticketflow/skill-groups$",
        SkillGroupViewSet.as_view({"get": "list", "post": "create"}),
        name="ticketflow-skill-group-list",
    ),
    re_path(r"^api/ticketflow/skill-groups/", include(skill_group_urlpatterns)),
]
PERMISSION_WHITE_REURL: dict[str, list[str]] = {}
