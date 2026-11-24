from rest_framework.routers import SimpleRouter

from tickets.assistant_views import AssistantFeedbackViewSet, AssistantInternalViewSet, AssistantSessionViewSet
from tickets.management_views import AccountViewSet, SkillGroupViewSet
from tickets.rating_views import TicketRatingViewSet
from tickets.views import TicketViewSet

router = SimpleRouter(trailing_slash=False)
router.register("", TicketViewSet, basename="ticket")
urlpatterns = [pattern for pattern in router.urls if pattern.name != "ticket-list"]

ratings_router = SimpleRouter(trailing_slash=False)
ratings_router.register("", TicketRatingViewSet, basename="ticket-rating")
ratings_urlpatterns = [pattern for pattern in ratings_router.urls if pattern.name != "ticket-rating-list"]

account_router = SimpleRouter(trailing_slash=False)
account_router.register("", AccountViewSet, basename="ticketflow-account")
account_urlpatterns = [pattern for pattern in account_router.urls if pattern.name != "ticketflow-account-list"]

skill_group_router = SimpleRouter(trailing_slash=False)
skill_group_router.register("", SkillGroupViewSet, basename="ticketflow-skill-group")
skill_group_urlpatterns = [
    pattern for pattern in skill_group_router.urls if pattern.name != "ticketflow-skill-group-list"
]

assistant_router = SimpleRouter(trailing_slash=False)
assistant_router.register("sessions", AssistantSessionViewSet, basename="assistant-session")
assistant_router.register("feedback", AssistantFeedbackViewSet, basename="assistant-feedback")
assistant_router.register("internal/sessions", AssistantInternalViewSet, basename="assistant-internal")
