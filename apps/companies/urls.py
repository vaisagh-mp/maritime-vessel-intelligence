from django.urls import path

from .overview_views import CompanyOverviewAPIView, CompanyVesselsAPIView
from .views import CompanyDetailAPIView, CompanyListCreateAPIView

urlpatterns = [
    path("", CompanyListCreateAPIView.as_view(), name="company-list"),
    # New read-only endpoints routed BEFORE <int:pk>
    path("overview/", CompanyOverviewAPIView.as_view(), name="company-overview"),
    path("<int:pk>/vessels/", CompanyVesselsAPIView.as_view(), name="company-vessels"),
    path("<int:pk>/", CompanyDetailAPIView.as_view(), name="company-detail"),
]
