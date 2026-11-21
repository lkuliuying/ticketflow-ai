from rest_framework.routers import SimpleRouter

from knowledge.views import ArticleViewSet

router = SimpleRouter(trailing_slash=False)
router.register("articles", ArticleViewSet, basename="knowledge-article")
urlpatterns = router.urls
