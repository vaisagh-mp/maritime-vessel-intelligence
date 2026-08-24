"""Opportunity dedup + zone classification (proximity-based at discovery time,
ETA-based once enrichment resolves a real ETA) + score recalculation."""
from datetime import timedelta

from django.utils import timezone

from apps.common.constants import ZONE_24H, ZONE_72H, ZONE_ANCHORAGE
from apps.opportunities.models import Opportunity
from services.scoring_service import calculate_score


def classify_zone_by_eta(eta, now=None) -> str:
    """ETA-based classification, used by enrichment once a real ETA is known.
    Boundary values: exactly 24h -> "24h", exactly 72h -> "72h", eta in the
    past or within 0h -> "anchorage"."""
    now = now or timezone.now()
    if eta is None:
        return ZONE_ANCHORAGE
    delta = eta - now
    if delta <= timedelta(hours=0):
        return ZONE_ANCHORAGE
    if delta <= timedelta(hours=24):
        return ZONE_24H
    if delta <= timedelta(hours=72):
        return ZONE_72H
    return ZONE_72H  # beyond 72h still bucketed as the widest known zone at MVP


def classify_zone_by_proximity() -> str:
    """Discovery only ever calls the area-scan endpoint for vessels already
    inside a port's anchorage geofence, so the initial classification is
    always "anchorage" — refined later by enrichment's ETA-based zone."""
    return ZONE_ANCHORAGE


def recalculate_score(opportunity):
    """Compute the current score via the scoring engine and persist it.
    Called from all trigger points — never duplicates the save logic."""
    opportunity.score = calculate_score(opportunity)
    opportunity.save(update_fields=["score", "updated_at"])
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
