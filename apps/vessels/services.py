"""Thin re-export so `apps.vessels.services` and the top-level
`services.vessel_service` stay in sync — the real implementation lives in
services/vessel_service.py to keep cross-domain business logic out of the
Django app package, per the project's service-layer architecture."""
from services.vessel_service import get_or_create_vessel  # noqa: F401
