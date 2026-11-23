from rest_framework.routers import SimpleRouter

from tickets.rating_views import TicketRatingViewSet
from tickets.views import TicketViewSet

router = SimpleRouter(trailing_slash=False)
router.register("", TicketViewSet, basename="ticket")
urlpatterns = [pattern for pattern in router.urls if pattern.name != "ticket-list"]

ratings_router = SimpleRouter(trailing_slash=False)
ratings_router.register("", TicketRatingViewSet, basename="ticket-rating")
ratings_urlpatterns = [pattern for pattern in ratings_router.urls if pattern.name != "ticket-rating-list"]
