from django.urls import path

from .latest import LatestArrivalsAPIView
from .summary import DashboardSummaryAPIView
from .views import (
    OpportunityDetailAPIView,
    OpportunityExportAPIView,
    OpportunityHistoryAPIView,
    OpportunityListAPIView,
    OpportunityNotesAPIView,
)

urlpatterns = [
    path("", OpportunityListAPIView.as_view(), name="opportunity-list"),
    path("summary/", DashboardSummaryAPIView.as_view(), name="opportunity-summary"),
    path("latest-arrivals/", LatestArrivalsAPIView.as_view(), name="opportunity-latest-arrivals"),
    path("export/", OpportunityExportAPIView.as_view(), name="opportunity-export"),
    path("<int:pk>/", OpportunityDetailAPIView.as_view(), name="opportunity-detail"),
    path("<int:pk>/notes/", OpportunityNotesAPIView.as_view(), name="opportunity-notes"),
    path("<int:pk>/history/", OpportunityHistoryAPIView.as_view(), name="opportunity-history"),
]
