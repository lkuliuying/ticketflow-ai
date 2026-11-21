from rest_framework.routers import SimpleRouter

from tickets.views import TicketViewSet

router = SimpleRouter(trailing_slash=False)
router.register("", TicketViewSet, basename="ticket")
urlpatterns = [pattern for pattern in router.urls if pattern.name != "ticket-list"]
