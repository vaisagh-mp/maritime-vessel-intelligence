"""
Lead scoring engine — rules-based, explainable 0–100+ scoring.

Pure function ``calculate_score(opportunity)`` inspects the Opportunity and its
related Vessel / Port / Company / VesselRelationship data and returns an integer
score.  No side effects — just a number out.

``get_band(score)`` maps a numeric score to a human-readable priority band
(HOT / HIGH / MEDIUM / LOW) via ``settings.SCORE_BANDS``.
"""
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from apps.common.constants import (
    CLOSED_STAGES,
    STAGE_CONTACTED,
    STAGE_LOST,
    STAGE_NEGOTIATION,
    STAGE_QUOTE_REQUESTED,
    STAGE_QUOTED,
    STAGE_REPLIED,
    STAGE_WON,
)

# Stages that count as "active pipeline" for the existing-relationship signal.
_ACTIVE_PIPELINE_STAGES = {
    STAGE_CONTACTED,
    STAGE_REPLIED,
    STAGE_QUOTE_REQUESTED,
    STAGE_QUOTED,
    STAGE_NEGOTIATION,
}

# Stages at or beyond "quote_requested" for the previous-enquiry signal.
_QUOTE_OR_BEYOND_STAGES = {
    STAGE_QUOTE_REQUESTED,
    STAGE_QUOTED,
    STAGE_NEGOTIATION,
    STAGE_WON,
    STAGE_LOST,
}


# ---------------------------------------------------------------------------
# Band helper
# ---------------------------------------------------------------------------

def get_band(score: int) -> str:
    """Map a numeric score to a priority band using ``settings.SCORE_BANDS``.

    The list is walked top-down; the first threshold that is ``<= score`` wins.
    Falls back to the last band if nothing matches (shouldn't happen with a
    0-threshold entry).
    """
    for threshold, label in settings.SCORE_BANDS:
        if score >= threshold:
            return label
    # Fallback — return the last band label (should be "LOW" with threshold 0).
    return settings.SCORE_BANDS[-1][1]


# ---------------------------------------------------------------------------
# Individual signal functions (private)
# ---------------------------------------------------------------------------

def _score_eta_zone(opportunity) -> int:
    """ETA / zone proximity signal: +30 for <24h / at anchorage, +20 for
    24-48h, +10 for 48-72h."""
    zone = opportunity.zone
    eta = opportunity.eta

    if zone == "24h":
        return 30
    if zone == "anchorage":
        # Vessel is already there — treat as immediate regardless of ETA.
        return 30

    # zone == "72h": use ETA to differentiate 24-48h vs 48-72h
    if eta is None:
        return 10  # No ETA in the 72h zone — assume distant, give minimum.

    now = timezone.now()
    hours_out = (eta - now).total_seconds() / 3600
    if hours_out <= 24:
        return 30
    if hours_out <= 48:
        return 20
    return 10


def _score_vessel_segment(vessel) -> int:
    """Relevant vessel segment: +20 for exact match, +10 for keyword match."""
    vessel_type = vessel.vessel_type or ""
    if not vessel_type:
        return 0

    segments = getattr(settings, "SCORING_RELEVANT_VESSEL_SEGMENTS", {})

    # Exact match (case-insensitive).
    exact_types = [t.lower() for t in segments.get("exact", [])]
    if vessel_type.lower() in exact_types:
        return 20

    # Keyword / substring match (case-insensitive).
    vt_lower = vessel_type.lower()
    for keyword in segments.get("keyword", []):
        if keyword.lower() in vt_lower:
            return 10

    return 0


def _score_priority_manager(vessel) -> int:
    """Priority ship manager account: +20 if the vessel has a manager
    relationship to a high-priority company."""
    has_priority = vessel.relationships.filter(
        role="manager", company__priority="high"
    ).exists()
    return 20 if has_priority else 0


def _score_existing_relationship(vessel, current_opportunity) -> int:
    """Existing relationship: +30 if a company linked to this vessel has a
    prior won Opportunity, +20 if a prior active-pipeline Opportunity exists
    (without being lost)."""
    from apps.opportunities.models import Opportunity

    company_ids = vessel.relationships.values_list("company_id", flat=True)
    if not company_ids:
        return 0

    # Find all vessels linked to the same companies.
    from apps.relationships.models import VesselRelationship
    related_vessel_ids = (
        VesselRelationship.objects
        .filter(company_id__in=company_ids)
        .values_list("vessel_id", flat=True)
    )

    # Prior opportunities for those vessels (excluding the current one).
    prior_opps = (
        Opportunity.objects
        .filter(vessel_id__in=related_vessel_ids)
        .exclude(pk=current_opportunity.pk)
    )

    if prior_opps.filter(stage=STAGE_WON).exists():
        return 30
    if prior_opps.filter(stage__in=_ACTIVE_PIPELINE_STAGES).exists():
        return 20
    return 0


def _score_verified_contact(vessel) -> int:
    """Verified decision-maker contact: +20 if any VesselRelationship for
    this vessel has verified=True."""
    has_verified = vessel.relationships.filter(verified=True).exists()
    return 20 if has_verified else 0


def _score_previous_enquiry(vessel, current_opportunity) -> int:
    """Previous enquiry / quote: +25 if the vessel or its companies have a
    prior Opportunity that reached quote_requested or beyond."""
    from apps.opportunities.models import Opportunity

    # Direct vessel history first.
    prior_vessel = (
        Opportunity.objects
        .filter(vessel=vessel, stage__in=_QUOTE_OR_BEYOND_STAGES)
        .exclude(pk=current_opportunity.pk)
    )
    if prior_vessel.exists():
        return 25

    # Company-linked vessel history.
    company_ids = vessel.relationships.values_list("company_id", flat=True)
    if company_ids:
        from apps.relationships.models import VesselRelationship
        related_vessel_ids = (
            VesselRelationship.objects
            .filter(company_id__in=company_ids)
            .values_list("vessel_id", flat=True)
        )
        prior_company = (
            Opportunity.objects
            .filter(vessel_id__in=related_vessel_ids, stage__in=_QUOTE_OR_BEYOND_STAGES)
            .exclude(pk=current_opportunity.pk)
        )
        if prior_company.exists():
            return 25

    return 0


def _score_large_fleet(vessel) -> int:
    """Large/strategic fleet relevance: +10 if vessel DWT exceeds the
    configured threshold."""
    threshold = getattr(settings, "SCORING_LARGE_FLEET_DWT_THRESHOLD", 50000)
    if vessel.dwt and vessel.dwt >= threshold:
        return 10
    return 0


def _score_recent_negative(vessel, current_opportunity) -> int:
    """Recent negative / closed interaction: -20 if the vessel or its
    companies have an Opportunity with stage='lost' in the configured window."""
    from apps.opportunities.models import Opportunity

    window_days = getattr(settings, "SCORING_RECENT_NEGATIVE_WINDOW_DAYS", 90)
    cutoff = timezone.now() - timedelta(days=window_days)

    # Direct vessel history.
    if (
        Opportunity.objects
        .filter(vessel=vessel, stage=STAGE_LOST, updated_at__gte=cutoff)
        .exclude(pk=current_opportunity.pk)
        .exists()
    ):
        return -20

    # Company-linked vessel history.
    company_ids = vessel.relationships.values_list("company_id", flat=True)
    if company_ids:
        from apps.relationships.models import VesselRelationship
        related_vessel_ids = (
            VesselRelationship.objects
            .filter(company_id__in=company_ids)
            .values_list("vessel_id", flat=True)
        )
        if (
            Opportunity.objects
            .filter(vessel_id__in=related_vessel_ids, stage=STAGE_LOST, updated_at__gte=cutoff)
            .exclude(pk=current_opportunity.pk)
            .exists()
        ):
            return -20

    return 0


# ---------------------------------------------------------------------------
# Main scoring function
# ---------------------------------------------------------------------------

def calculate_score(opportunity) -> int:
    """Compute the lead score for an Opportunity by summing all applicable
    signal scores.  Returns an integer clamped to >= 0."""
    vessel = opportunity.vessel

    score = 0
    score += _score_eta_zone(opportunity)
    score += _score_vessel_segment(vessel)
    score += _score_priority_manager(vessel)
    score += _score_existing_relationship(vessel, opportunity)
    score += _score_verified_contact(vessel)
    score += _score_previous_enquiry(vessel, opportunity)
    score += _score_large_fleet(vessel)
    score += _score_recent_negative(vessel, opportunity)

    return max(score, 0)
