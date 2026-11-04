from django.urls import path

from .views import (
    VesselRelationshipDetailAPIView,
    VesselRelationshipListAPIView,
)

urlpatterns = [
    path("", VesselRelationshipListAPIView.as_view(), name="vessel-relationship-list"),
    path("<int:pk>/", VesselRelationshipDetailAPIView.as_view(), name="vessel-relationship-detail"),
]
