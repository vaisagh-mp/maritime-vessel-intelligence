from django.urls import path

from .views import (
    VesselRelationshipDetailAPIView,
    VesselRelationshipListAPIView,
    VesselRelationshipUnverifyAPIView,
    VesselRelationshipVerifyAPIView,
)

urlpatterns = [
    path("", VesselRelationshipListAPIView.as_view(), name="vessel-relationship-list"),
    path("<int:pk>/verify/", VesselRelationshipVerifyAPIView.as_view(), name="vessel-relationship-verify"),
    path("<int:pk>/unverify/", VesselRelationshipUnverifyAPIView.as_view(), name="vessel-relationship-unverify"),
    path("<int:pk>/", VesselRelationshipDetailAPIView.as_view(), name="vessel-relationship-detail"),
]
