from rest_framework.routers import DefaultRouter

from .views import VesselRelationshipViewSet

router = DefaultRouter()
router.register("", VesselRelationshipViewSet, basename="vessel-relationship")

urlpatterns = router.urls
