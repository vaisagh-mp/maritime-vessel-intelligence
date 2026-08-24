from rest_framework.routers import DefaultRouter

from .views import EnrichmentLogViewSet

router = DefaultRouter()
router.register("", EnrichmentLogViewSet, basename="enrichment-log")

urlpatterns = router.urls
