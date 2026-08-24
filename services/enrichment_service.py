"""Orchestrates the two enrichment calls (ETA/location + management), updates
the vessel's open Opportunity, resolves company relationships, and logs every
call — success or failure — to EnrichmentLog for auditable credit spend."""
import logging

from apps.common.constants import ENRICHMENT_ENDPOINT_LOCATION, ENRICHMENT_ENDPOINT_MANAGEMENT
from apps.enrichment.models import EnrichmentLog
from apps.opportunities.models import Opportunity
from apps.vessels.models import Vessel
from integrations.datadocked.exceptions import DataDockedError
from integrations.datadocked.location import fetch_vessel_location
from integrations.datadocked.management import fetch_vessel_management

from .company_service import apply_management_data
from .opportunity_service import update_opportunity_eta

logger = logging.getLogger("vessel_intel")

LOCATION_CREDITS = 1
MANAGEMENT_CREDITS = 1


def _lookup_key(vessel: Vessel) -> str:
    return vessel.imo or vessel.mmsi


def _log(vessel, endpoint, success, credits_spent, error_message=""):
    EnrichmentLog.objects.create(
        vessel=vessel,
        endpoint_called=endpoint,
        success=success,
        credits_spent=credits_spent if success else 0,
        error_message=error_message,
    )


def enrich_vessel(vessel_id: int) -> dict:
    vessel = Vessel.objects.get(pk=vessel_id)
    key = _lookup_key(vessel)
    result = {"vessel_id": vessel_id, "location": None, "management": None}

    # --- 2a: ETA / destination ---
    try:
        location = fetch_vessel_location(key)
        _log(vessel, ENRICHMENT_ENDPOINT_LOCATION, True, LOCATION_CREDITS)
        result["location"] = location

        if location.get("imo") and not vessel.imo:
            vessel.imo = location["imo"]
            vessel.save(update_fields=["imo", "updated_at"])

        open_opportunity = (
            Opportunity.objects.filter(vessel=vessel)
            .exclude(stage__in=["won", "lost"])
            .order_by("-detected_at")
            .first()
        )
        if open_opportunity and location.get("eta") is not None:
            update_opportunity_eta(open_opportunity, location["eta"])
    except DataDockedError as exc:
        logger.warning("Location enrichment failed for vessel %s: %s", vessel_id, exc)
        _log(vessel, ENRICHMENT_ENDPOINT_LOCATION, False, 0, str(exc))

    # --- 2b: Ownership / management ---
    try:
        management = fetch_vessel_management(key)
        _log(vessel, ENRICHMENT_ENDPOINT_MANAGEMENT, True, MANAGEMENT_CREDITS)
        result["management"] = management
        apply_management_data(vessel, management)
    except DataDockedError as exc:
        logger.warning("Management enrichment failed for vessel %s: %s", vessel_id, exc)
        _log(vessel, ENRICHMENT_ENDPOINT_MANAGEMENT, False, 0, str(exc))

    return result
