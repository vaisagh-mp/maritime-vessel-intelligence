"""Celery task wrapper for enrichment — kept on its own queue/schedule and
never called from inside the discovery loop, so a large discovery batch never
fires hundreds of paid enrichment calls at once.

Enabling this requires Celery/Redis (see README). Until then, use the
`enrich_vessel` service function directly, or the manual
`POST /api/v1/vessels/{id}/enrich/` endpoint.
"""
try:
    from celery import shared_task
except ImportError:  # Celery not installed yet — Phase 1 can run without it.
    def shared_task(func):
        return func

from services.enrichment_service import enrich_vessel as _enrich_vessel


@shared_task
def enrich_vessel(vessel_id):
    return _enrich_vessel(vessel_id)
