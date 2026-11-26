"""
Top-level API URL routing: mounts each domain app's URLs under /api/v1/<resource>/.
"""
from django.urls import include, path
from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
    TokenVerifyView,
)

from apps.common.auth_views import MeView

urlpatterns = [
    # --- Authentication ---
    path("auth/token/", TokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("auth/token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("auth/token/verify/", TokenVerifyView.as_view(), name="token_verify"),
    path("auth/me/", MeView.as_view(), name="auth_me"),
    # --- Domain resources ---
    path("business-developers/", include("apps.common.bd_urls")),
    path("ports/", include("apps.ports.urls")),
    path("companies/", include("apps.companies.urls")),
    path("vessels/", include("apps.vessels.urls")),
    path("observations/", include("apps.observations.urls")),
    path("opportunities/", include("apps.opportunities.urls")),
    path("enrichment/", include("apps.enrichment.urls")),
    path("ingest/", include("apps.enrichment.ingest_urls")),
    path("relationships/", include("apps.relationships.urls")),
    path("outreach/", include("apps.outreach.urls")),
]
