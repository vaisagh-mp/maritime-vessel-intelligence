"""Entry point used by the vessels app's manual-enrichment API action.
Delegates to the real orchestration in services/enrichment_service.py."""
from services.enrichment_service import enrich_vessel


def trigger_manual_enrichment(vessel):
    """Runs enrichment inline for now (Phase 1 has no Celery wired in by
    default — see apps/enrichment/tasks.py for the queued version once
    Celery/Redis is enabled)."""
    result = enrich_vessel(vessel.id)
    return {"vessel_id": vessel.id, "triggered": True, "result": result}
