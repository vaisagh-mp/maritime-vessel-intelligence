"""Expected-arrivals discovery task: polls every active Port via DataDocked's
port-calls-by-port?search_type=expected endpoint, applies the same
type-exclusion filter as area-scan discovery, upserts vessels by MMSI
(populating dwt when not yet set), opens Opportunities with ETA-derived
zones, and logs every paid page fetch to EnrichmentLog.

Key differences from tasks/discovery.py:
  - Uses port.un_locode as the query key — no geofence coordinates.
  - No VesselObservation is created (response has no lat/long and those
    fields are non-nullable by design).
  - Zone is classified by ETA, not by geofence proximity.
  - dwt is backfilled from the `dw` field when not already set — closes the
    gap that prevented the scoring engine's large-fleet signal from firing.
  - EnrichmentLog rows are port-scoped (vessel=None), one row per page fetched.

Schedule separately from run_discovery — recommended daily given the 50-credit
per-page cost.
"""
import logging

from apps.common.constants import ENRICHMENT_ENDPOINT_PORT_CALLS_EXPECTED
from apps.enrichment.models import EnrichmentLog
from apps.ports.models import Port
from apps.vessels.models import Vessel
from apps.vessels.validators import is_aid_to_navigation_mmsi, is_vessel_type_excluded
from integrations.datadocked.exceptions import DataDockedError
from integrations.datadocked.port_calls import fetch_expected_arrivals
from services.opportunity_service import (
    classify_zone_by_eta,
    get_or_create_open_opportunity,
)

logger = logging.getLogger("vessel_intel")

PORT_CALLS_CREDITS_PER_PAGE = 50


def _log_page(port, success, error_message=""):
    """Log one EnrichmentLog row for a single page fetch against a port."""
    EnrichmentLog.objects.create(
        vessel=None,
        port=port,
        endpoint_called=ENRICHMENT_ENDPOINT_PORT_CALLS_EXPECTED,
        success=success,
        credits_spent=PORT_CALLS_CREDITS_PER_PAGE if success else 0,
        error_message=error_message,
    )


def run_expected_arrivals_for_port(port: Port) -> dict:
    """Run the expected-arrivals discovery for a single port.

    Returns a stats dict mirroring the shape from tasks/discovery.py:
        {port, seen, new_vessels, new_opportunities, excluded, errors}
    """
    stats = {
        "port": port.name,
        "seen": 0,
        "new_vessels": 0,
        "new_opportunities": 0,
        "excluded": 0,
        "errors": 0,
    }

    try:
        vessels, pages_fetched = fetch_expected_arrivals(port)
    except DataDockedError as exc:
        logger.error(
            "Expected-arrivals fetch failed for port %s (%s): %s",
            port.name, port.un_locode, exc,
        )
        _log_page(port, success=False, error_message=str(exc))
        stats["errors"] += 1
        return stats

    # Log one row per page successfully fetched (each costs 50 credits)
    for _ in range(pages_fetched):
        _log_page(port, success=True)

    for raw in vessels:
        stats["seen"] += 1

        mmsi = raw.get("mmsi")
        if not mmsi:
            logger.warning(
                "Expected-arrivals: record missing mmsi for port %s, skipping: %s",
                port.name, raw,
            )
            stats["excluded"] += 1
            continue

        # AtoN structural check (MMSI prefix 99)
        if is_aid_to_navigation_mmsi(str(mmsi)):
            stats["excluded"] += 1
            continue

        # Type-exclusion: field is `type` here, not `typeSpecific`
        vessel_type = raw.get("type", "") or ""
        if is_vessel_type_excluded(vessel_type):
            stats["excluded"] += 1
            continue

        # --- Vessel upsert ---
        name = raw.get("name", "") or ""
        vessel, created = Vessel.objects.get_or_create(
            mmsi=str(mmsi),
            defaults={"name": name, "vessel_type": vessel_type},
        )

        if not created:
            # Update mutable fields if they've changed
            changed = []
            if name and vessel.name != name:
                vessel.name = name
                changed.append("name")
            if vessel_type and vessel.vessel_type != vessel_type:
                vessel.vessel_type = vessel_type
                changed.append("vessel_type")
            if changed:
                vessel.save(update_fields=changed + ["updated_at"])
        else:
            stats["new_vessels"] += 1

        # Backfill dwt from the `dw` field — only when not already set.
        # This closes the gap: no existing integration populates dwt, so the
        # scoring engine's "large fleet relevance +10" signal has never fired.
        dw = raw.get("dw")
        if dw is not None and vessel.dwt is None:
            try:
                vessel.dwt = float(dw)
                vessel.save(update_fields=["dwt", "updated_at"])
            except (TypeError, ValueError):
                logger.warning(
                    "Expected-arrivals: could not cast dw=%r to float for MMSI %s",
                    dw, mmsi,
                )

        # --- Opportunity ---
        parsed_eta = raw.get("eta")
        zone = classify_zone_by_eta(parsed_eta)

        _, opp_created = get_or_create_open_opportunity(vessel, port, zone=zone)
        if opp_created:
            stats["new_opportunities"] += 1

    return stats


def run_expected_arrivals() -> list:
    """Run expected-arrivals discovery for every active port.

    Returns per-port stats list. Schedule independently from run_discovery
    (recommended: daily) — never bundle into run_discovery's cron, as the
    50-credit-per-page cost makes this substantially more expensive.
    """
    results = []
    for port in Port.objects.filter(active=True):
        results.append(run_expected_arrivals_for_port(port))
    return results
