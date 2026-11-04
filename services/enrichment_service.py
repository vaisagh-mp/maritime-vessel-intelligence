"""Orchestrates vessel enrichment — location/ETA and management/ownership.

The Kpler integration that provides the actual data arrives in Steps 4 to 8.
Until then, enrich_vessel() returns a stub result and logs an info message
rather than creating EnrichmentLog rows (no call was made, so no cost to
track).
"""
import logging

from apps.vessels.models import Vessel

logger = logging.getLogger("vessel_intel")


def enrich_vessel(vessel_id: int) -> dict:
    """Enrich a vessel with location and management data.

    Returns a dict with keys ``vessel_id``, ``location``, ``management``, and
    ``status``.  When no data provider is configured the latter is set to
    ``"no_provider_configured"`` and the other two values are ``None``.

    The Kpler implementation arrives in Steps 4 to 8.
    """
    # Confirm the vessel exists so callers still get DoesNotExist on a bad id.
    Vessel.objects.get(pk=vessel_id)

    logger.info(
        "enrich_vessel called for vessel_id=%s — no provider configured; "
        "Kpler implementation arrives in Steps 4 to 8.",
        vessel_id,
    )
    return {
        "vessel_id": vessel_id,
        "location": None,
        "management": None,
        "status": "no_provider_configured",
    }
