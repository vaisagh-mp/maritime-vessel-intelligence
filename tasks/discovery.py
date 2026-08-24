"""Discovery task: polls every active Port via DataDocked's area-scan
endpoint, applies the type-exclusion filter, upserts vessels by MMSI, appends
an observation, and opens an Opportunity if one isn't already open for that
vessel+port. Enrichment is never triggered from inside this loop — it only
records which newly-created vessels are eligible, and the caller (management
command / Celery beat) decides when to fire enrichment on its own
queue/schedule.
"""
import logging

from apps.ports.models import Port
from integrations.datadocked.discovery import fetch_vessels_by_area
from integrations.datadocked.exceptions import DataDockedError
from services.observation_service import record_observation
from services.opportunity_service import (
    get_or_create_open_opportunity,
    touch_opportunity_zone_from_proximity,
)
from services.vessel_service import get_or_create_vessel

logger = logging.getLogger("vessel_intel")


def run_discovery_for_port(port: Port) -> dict:
    stats = {"port": port.name, "seen": 0, "new_vessels": 0, "new_opportunities": 0, "excluded": 0, "errors": 0}
    newly_created_vessel_ids = []

    try:
        raw_vessels = fetch_vessels_by_area(port)
    except DataDockedError as exc:
        logger.error("Discovery scan failed for port %s: %s", port.name, exc)
        stats["errors"] += 1
        return {**stats, "newly_created_vessel_ids": newly_created_vessel_ids}

    for raw_vessel in raw_vessels:
        stats["seen"] += 1
        vessel, created = get_or_create_vessel(raw_vessel)
        if vessel is None:
            stats["excluded"] += 1
            continue
        if created:
            stats["new_vessels"] += 1
            newly_created_vessel_ids.append(vessel.id)

        record_observation(vessel, raw_vessel)

        opp, opp_created = get_or_create_open_opportunity(vessel, port)
        if opp_created:
            stats["new_opportunities"] += 1
        else:
            # Physical presence inside the geofence is more authoritative than
            # any earlier ETA projection — upgrade stale zones to "anchorage".
            touch_opportunity_zone_from_proximity(opp)

    return {**stats, "newly_created_vessel_ids": newly_created_vessel_ids}


def run_discovery() -> list:
    """Runs discovery for every active port. Returns per-port stats.

    Newly created vessels that survived the type filter are eligible for
    enrichment — the caller (see apps/common/management/commands/run_discovery.py)
    decides whether to fire it immediately, queue it, or leave it manual.
    """
    results = []
    for port in Port.objects.filter(active=True):
        results.append(run_discovery_for_port(port))
    return results
