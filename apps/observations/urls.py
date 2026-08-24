from rest_framework.routers import DefaultRouter

from .views import VesselObservationViewSet

router = DefaultRouter()
router.register("", VesselObservationViewSet, basename="vessel-observation")

urlpatterns = router.urls
