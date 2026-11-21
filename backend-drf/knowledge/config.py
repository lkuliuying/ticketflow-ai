from django.urls import include, path, re_path
from django.urls.converters import UUIDConverter

from knowledge.views import TicketAiContextView

URLPATTERNS = [
    path("api/knowledge/", include("knowledge.urls")),
    re_path(
        rf"^api/tickets/(?P<pk>{UUIDConverter.regex})/ai-context$",
        TicketAiContextView.as_view({"get": "context"}),
        name="ticket-ai-context",
    ),
]
PERMISSION_WHITE_REURL: dict[str, list[str]] = {}
