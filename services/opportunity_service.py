"""Opportunity dedup + zone classification (proximity-based at discovery time,
ETA-based once enrichment resolves a real ETA) + score recalculation."""
from datetime import timedelta

from django.utils import timezone

from apps.common.constants import (
    PORT_AREA_ANCHORAGE,
    PORT_AREA_ANCHORAGE_BOUND,
    PORT_AREA_INBOUND,
    ZONE_24H,
    ZONE_72H,
    ZONE_ANCHORAGE,
    ZONE_ANCHORAGE_BOUND,
)
from apps.opportunities.models import Opportunity
from services.scoring_service import calculate_score, calculate_score_and_reason


def classify_zone_by_eta(eta, now=None) -> str:
    """ETA-based classification for vessels that are on their way in.

    Boundary values: exactly 24h -> "24h", exactly 72h -> "72h".
    An ETA in the past (or exactly now) means "arriving now", so it stays in
    the "24h" zone (the card still shows "ETA passed"). A passed ETA is NOT
    evidence that the vessel is at anchor: the anchorage zone is only used when
    an observation says so (see ``resolve_zone``).

    ``eta=None`` keeps the old discovery-time behaviour ("anchorage"), because
    the legacy discovery path only ever sees vessels inside the anchorage geofence.
    """
    now = now or timezone.now()
    if eta is None:
        return ZONE_ANCHORAGE
    delta = eta - now
    if delta <= timedelta(hours=24):
        return ZONE_24H
    if delta <= timedelta(hours=72):
        return ZONE_72H
    return ZONE_72H  # beyond 72h still bucketed as the widest known zone at MVP


def resolve_zone(old_zone, eta, latest_port_area=None, now=None) -> str:
    """Single place that decides an open lead's zone from the latest evidence.

    Used by ``rescore_opportunities`` (and usable by any other caller).

    1. Latest observation says anchorage       -> anchorage
    2. Latest observation says anchorage bound -> anchorage bound
       (unless the lead is already in anchorage)
    3. Latest observation says inbound         -> by ETA, even if the lead was
       stored as anchorage (a vessel still inbound cannot be at anchor)
    4. Anything else (no observation, in port, unknown) -> keep an existing
       anchorage zone; otherwise by ETA when one is known; otherwise unchanged.
    """
    if latest_port_area == PORT_AREA_ANCHORAGE:
        return ZONE_ANCHORAGE
    if latest_port_area == PORT_AREA_ANCHORAGE_BOUND:
        return old_zone if old_zone == ZONE_ANCHORAGE else ZONE_ANCHORAGE_BOUND
    if latest_port_area == PORT_AREA_INBOUND and eta is not None:
        return classify_zone_by_eta(eta, now)
    if eta is not None and old_zone != ZONE_ANCHORAGE:
        return classify_zone_by_eta(eta, now)
    return old_zone


def classify_zone_by_proximity() -> str:
    """Discovery only ever calls the area-scan endpoint for vessels already
    inside a port's anchorage geofence, so the initial classification is
    always "anchorage" — refined later by enrichment's ETA-based zone."""
    return ZONE_ANCHORAGE


def recalculate_score(opportunity):
    """Compute the current score and lead_reason via the scoring engine and persist them.
    Called from all trigger points — never duplicates the save logic."""
    score, reason = calculate_score_and_reason(opportunity)
    opportunity.score = score
    opportunity.lead_reason = reason
    opportunity.save(update_fields=["score", "lead_reason", "updated_at"])
    return opportunity


def get_or_create_open_opportunity(vessel, port, zone=None):
    """Creates an Opportunity only if none is already open (stage not in
    won/lost) for this vessel+port combination — never duplicates."""
    existing = Opportunity.objects.open_for(vessel, port).first()
    if existing:
        return existing, False

    opportunity = Opportunity.objects.create(
        vessel=vessel,
        port=port,
        zone=zone or classify_zone_by_proximity(),
    )
    recalculate_score(opportunity)
    return opportunity, True


def touch_opportunity_zone_from_proximity(opportunity) -> bool:
    """Upgrade an existing open Opportunity's zone to ``"anchorage"`` when
    area-scan discovery physically observes the vessel inside the port geofence.

    Physical presence is a more authoritative signal than any prior ETA
    projection, so it always wins. If the zone is already ``"anchorage"``
    this is a no-op — the score is NOT recalculated redundantly.

    Returns ``True`` if the zone was updated (and score recalculated),
    ``False`` if it was already ``"anchorage"`` and nothing changed.
    """
    if opportunity.zone == ZONE_ANCHORAGE:
        return False
    opportunity.zone = ZONE_ANCHORAGE
    opportunity.save(update_fields=["zone", "updated_at"])
    recalculate_score(opportunity)
    return True


def update_opportunity_eta(opportunity, eta):
    """Called by enrichment once a real ETA is known: sets `eta` and
    reclassifies `zone`, replacing the discovery-time proximity guess,
    then recalculates the score (ETA/zone signals may have changed)."""
    opportunity.eta = eta
    opportunity.zone = classify_zone_by_eta(eta)
    opportunity.save(update_fields=["eta", "zone", "updated_at"])
    recalculate_score(opportunity)
    return opportunity


def _format_lead_reason(port, lead: dict, port_area: str) -> str:
    """Format short human-readable lead reason string (max 200 chars)."""
    if port_area == ZONE_ANCHORAGE:
        text = f"At {port.name.upper()} ANCH since last signal"
    elif port_area in (PORT_AREA_ANCHORAGE_BOUND, "anchorage_bound"):
        eta_val = lead.get("eta")
        eta_str = eta_val.strftime("%Y-%m-%d %H:%M UTC") if eta_val else "unknown"
        src_str = lead.get("eta_source") or "unknown"
        port_code = port.un_locode or port.name
        text = f"Anchorage bound to {port_code}, ETA {eta_str} ({src_str})"
    elif port_area == "inbound":
        eta_val = lead.get("eta")
        eta_str = eta_val.strftime("%Y-%m-%d %H:%M UTC") if eta_val else "unknown"
        src_str = lead.get("eta_source") or "unknown"
        port_code = port.un_locode or port.name
        text = f"Inbound to {port_code}, ETA {eta_str} ({src_str})"
    else:
        text = f"Area {port_area} at {port.un_locode or port.name}"

    if lead.get("came_from_target_port"):
        target = lead["came_from_target_port"]
        text += f" | from {target}"

    return text[:200]


def apply_lead(
    vessel,
    port,
    lead: dict,
    port_area: str,
    horizon_hours: int = 72,
) -> tuple[Opportunity | None, str]:
    """Apply expected arrivals lead intelligence to Opportunity records.
    Returns (opportunity, "created" | "updated" | "skipped").

    Eligibility rules:
    - port_area == "anchorage": eligible, zone = ZONE_ANCHORAGE.
    - port_area == "anchorage_bound" and lead["eta"] is not None and 0 < hours_to_eta <= horizon_hours:
      eligible, zone = ZONE_ANCHORAGE_BOUND.
    - port_area == "inbound" and lead["eta"] is not None and 0 < hours_to_eta <= horizon_hours:
      eligible, zone classified by classify_zone_by_eta(lead["eta"]).
    - Everything else: "skipped" (returns (None, "skipped")).

    Open Opportunity handling:
    - If an open opportunity exists, update it (eta, eta_source, is_inbound, lead_reason).
      If new area is anchorage, touch_opportunity_zone_from_proximity.
      If existing zone is already anchorage, never move it back to 24h or 72h.
      Recalculate score only when zone or ETA changed.
    - If none exists, get_or_create_open_opportunity with zone, set fields, and recalculate score.
    """
    zone = None
    if port_area == ZONE_ANCHORAGE:
        zone = ZONE_ANCHORAGE
    elif port_area in (PORT_AREA_ANCHORAGE_BOUND, "anchorage_bound"):
        eta = lead.get("eta")
        hours_to_eta = lead.get("hours_to_eta")
        if eta is not None and hours_to_eta is not None and 0 < hours_to_eta <= horizon_hours:
            zone = ZONE_ANCHORAGE_BOUND
        else:
            return None, "skipped"
    elif port_area == "inbound":
        eta = lead.get("eta")
        hours_to_eta = lead.get("hours_to_eta")
        if eta is not None and hours_to_eta is not None and 0 < hours_to_eta <= horizon_hours:
            zone = classify_zone_by_eta(eta)
        else:
            return None, "skipped"
    else:
        return None, "skipped"

    lead_reason = _format_lead_reason(port, lead, port_area)
    existing = Opportunity.objects.open_for(vessel, port).first()

    if existing:
        old_zone = existing.zone
        old_eta = existing.eta

        existing.eta = lead.get("eta")
        existing.eta_source = lead.get("eta_source", "") or ""
        existing.is_inbound = bool(lead.get("is_inbound", False))
        existing.lead_reason = lead_reason
        if lead.get("came_from_target_port"):
            existing.came_from_target_port = lead["came_from_target_port"]

        if port_area == ZONE_ANCHORAGE:
            touch_opportunity_zone_from_proximity(existing)
        elif port_area in (PORT_AREA_ANCHORAGE_BOUND, "anchorage_bound"):
            if existing.zone != ZONE_ANCHORAGE:
                existing.zone = ZONE_ANCHORAGE_BOUND
        else:
            if existing.zone not in (ZONE_ANCHORAGE, ZONE_ANCHORAGE_BOUND):
                existing.zone = zone

        zone_or_eta_changed = (existing.zone != old_zone or existing.eta != old_eta)
        if zone_or_eta_changed:
            recalculate_score(existing)

        existing.save(
            update_fields=[
                "eta",
                "eta_source",
                "is_inbound",
                "lead_reason",
                "zone",
                "updated_at",
            ]
        )
        return existing, "updated"

    # New opportunity
    opportunity, _ = get_or_create_open_opportunity(vessel, port, zone=zone)
    opportunity.eta = lead.get("eta")
    opportunity.eta_source = lead.get("eta_source", "") or ""
    opportunity.is_inbound = bool(lead.get("is_inbound", False))
    opportunity.lead_reason = lead_reason
    if lead.get("came_from_target_port"):
        opportunity.came_from_target_port = lead["came_from_target_port"]
    opportunity.save(
        update_fields=[
            "eta",
            "eta_source",
            "is_inbound",
            "lead_reason",
            "updated_at",
        ]
    )
    recalculate_score(opportunity)
    return opportunity, "created"

