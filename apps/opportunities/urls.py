from django.urls import path

from .views import (
    OpportunityDetailAPIView,
    OpportunityHistoryAPIView,
    OpportunityListAPIView,
    OpportunityNotesAPIView,
)

urlpatterns = [
    path("", OpportunityListAPIView.as_view(), name="opportunity-list"),
    path("<int:pk>/", OpportunityDetailAPIView.as_view(), name="opportunity-detail"),
    path("<int:pk>/notes/", OpportunityNotesAPIView.as_view(), name="opportunity-notes"),
    path("<int:pk>/history/", OpportunityHistoryAPIView.as_view(), name="opportunity-history"),
]
