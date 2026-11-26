from django.urls import path

from .refresh_views import IngestRefreshView, IngestRunDetailView, IngestStatusView, VesselOwnerLookupView

urlpatterns = [
    path("refresh/", IngestRefreshView.as_view(), name="ingest-refresh"),
    path("status/", IngestStatusView.as_view(), name="ingest-status"),
    path("vessels/<int:pk>/lookup-owner/", VesselOwnerLookupView.as_view(), name="vessel-owner-lookup"),
    path("runs/<int:pk>/", IngestRunDetailView.as_view(), name="ingest-run"),
]
