"""
Lead scoring engine — rules-based, explainable 0–100 scoring.

Pure function ``calculate_score(opportunity)`` inspects the Opportunity and its
related Vessel / Port / Company / VesselRelationship data and returns an integer
score clamped to [0, 100].

``calculate_score_and_reason(opportunity)`` returns ``(score, lead_reason)``.

``get_band(score)`` maps a numeric score to a human-readable priority band
(HOT / HIGH / MEDIUM / LOW) via ``settings.SCORE_BANDS``.
"""
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from apps.common.constants import (
    CLOSED_STAGES,
    PRIORITY_HIGH,
    RELATIONSHIP_ROLE_BENEFICIAL_OWNER,
    RELATIONSHIP_ROLE_COMMERCIAL_MANAGER,
    RELATIONSHIP_ROLE_ISM_MANAGER,
    RELATIONSHIP_ROLE_MANAGER,
    RELATIONSHIP_ROLE_OPERATOR,
    RELATIONSHIP_ROLE_OWNER,
    RELATIONSHIP_ROLE_REGISTERED_OWNER,
    RELATIONSHIP_ROLE_TECHNICAL_MANAGER,
    STAGE_CONTACTED,
    STAGE_LOST,
    STAGE_NEGOTIATION,
    STAGE_QUOTE_REQUESTED,
    STAGE_QUOTED,
    STAGE_REPLIED,
    STAGE_WON,
    ZONE_24H,
    ZONE_72H,
    ZONE_ANCHORAGE,
    ZONE_ANCHORAGE_BOUND,
)

# ---------------------------------------------------------------------------
# Centralized scoring weights & thresholds
# ---------------------------------------------------------------------------

SCORING_WEIGHTS = {
    # Zone proximity weights: anchorage highest, anchorage bound next, in port, then inbound
    "zone": {
        "anchorage": 30,
        "anchorage_bound": 25,
        "in_port": 20,
        "inbound_24h": 15,
        "inbound_48h": 10,
        "inbound_72h": 5,
    },
    # Vessel size based on GRT (replaces old DWT fleet threshold)
    "size_grt": {
        "tier_1_min": 3000,
        "tier_1_max": 9999,
        "tier_1_points": 4,
        "tier_2_min": 10000,
        "tier_2_max": 19999,
        "tier_2_points": 8,
        "tier_3_min": 20000,
        "tier_3_max": 49999,
        "tier_3_points": 12,
        "tier_4_min": 50000,
        "tier_4_points": 15,
    },
    # Pilot port origin & repeat caller
    "origin_target_port": 8,
    "repeat_caller": 5,
    "origin_repeat_cap": 13,
    "repeat_caller_min_obs": 2,
    "repeat_caller_window_days": 90,
    # Manager and owner contact quality (best manager and best owner count, not the sum).
    # Scored from the contact data we actually hold, not from the manual priority field.
    "manager_contacts": {"website_and_email": 20, "website_or_email": 12, "name_only": 6},
    "owner_contacts": {"email": 8, "name_only": 4},
    # Small bonus when a person has set a related company to priority "high".
    "priority_high_bonus": 5,
    # Cap for manager + owner + priority bonus together.
    "contacts_group_cap": 28,
    # Vessel segment
    "vessel_segment_exact": 20,
    "vessel_segment_keyword": 10,
    # Existing relationship
    "existing_relationship_won": 30,
    "existing_relationship_pipeline": 20,
    # Verified contact
    "verified_contact": 20,
    # Previous enquiry / quote
    "previous_enquiry": 25,
    # Recent negative interaction
    "recent_negative": -20,
    "recent_negative_window_days": 90,
    # Cap and floor
    "score_max": 100,
    "score_min": 0,
}

# Roles qualifying as manager for the priority manager signal
MANAGER_ROLES = {
    RELATIONSHIP_ROLE_TECHNICAL_MANAGER,
    RELATIONSHIP_ROLE_ISM_MANAGER,
    RELATIONSHIP_ROLE_COMMERCIAL_MANAGER,
    RELATIONSHIP_ROLE_OPERATOR,
    RELATIONSHIP_ROLE_MANAGER,
}

# Roles qualifying as owner for the owner-contact signal
OWNER_ROLES = {
    RELATIONSHIP_ROLE_REGISTERED_OWNER,
    RELATIONSHIP_ROLE_BENEFICIAL_OWNER,
    RELATIONSHIP_ROLE_OWNER,
}

# When two manager roles score the same, name the first one in this order.
_MANAGER_ROLE_PREFERENCE = [
    RELATIONSHIP_ROLE_TECHNICAL_MANAGER,
    RELATIONSHIP_ROLE_ISM_MANAGER,
    RELATIONSHIP_ROLE_COMMERCIAL_MANAGER,
    RELATIONSHIP_ROLE_OPERATOR,
    RELATIONSHIP_ROLE_MANAGER,
]

_OWNER_ROLE_PREFERENCE = [
    RELATIONSHIP_ROLE_REGISTERED_OWNER,
    RELATIONSHIP_ROLE_BENEFICIAL_OWNER,
    RELATIONSHIP_ROLE_OWNER,
]

# Pilot / target ports
TARGET_PORT_UNLOCODES = {"AEFJR", "SGSIN"}
TARGET_PORT_NAMES = {"FUJAIRAH", "SINGAPORE"}

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
    return settings.SCORE_BANDS[-1][1]


# ---------------------------------------------------------------------------
# Individual signal functions
# ---------------------------------------------------------------------------

def _score_eta_zone(opportunity) -> int:
    """ETA / zone proximity signal:
    Anchorage highest (30), anchorage bound next (25), in port (20), then inbound (15 / 10 / 5).
    """
    zone = getattr(opportunity, "zone", "")
    eta = getattr(opportunity, "eta", None)

    if zone == ZONE_ANCHORAGE:
        return SCORING_WEIGHTS["zone"]["anchorage"]
    if zone == ZONE_ANCHORAGE_BOUND:
        return SCORING_WEIGHTS["zone"]["anchorage_bound"]
    if zone == "in_port":
        return SCORING_WEIGHTS["zone"]["in_port"]

    if zone == ZONE_24H:
        return SCORING_WEIGHTS["zone"]["inbound_24h"]

    if eta is None:
        return SCORING_WEIGHTS["zone"]["inbound_72h"]

    now = timezone.now()
    hours_out = (eta - now).total_seconds() / 3600
    if hours_out <= 24:
        return SCORING_WEIGHTS["zone"]["inbound_24h"]
    if hours_out <= 48:
        return SCORING_WEIGHTS["zone"]["inbound_48h"]
    return SCORING_WEIGHTS["zone"]["inbound_72h"]


def _score_vessel_size(vessel) -> int:
    """Vessel size from GRT:
    3,000 to 9,999: 4; 10,000 to 19,999: 8; 20,000 to 49,999: 12; 50,000+: 15.
    Missing GRT gives 0 points.
    """
    if vessel.grt is None:
        return 0

    grt = vessel.grt
    cfg = SCORING_WEIGHTS["size_grt"]

    if grt >= cfg["tier_4_min"]:
        return cfg["tier_4_points"]
    if grt >= cfg["tier_3_min"]:
        return cfg["tier_3_points"]
    if grt >= cfg["tier_2_min"]:
        return cfg["tier_2_points"]
    if grt >= cfg["tier_1_min"]:
        return cfg["tier_1_points"]

    return 0


def _score_large_fleet(vessel) -> int:
    """Backward compatibility alias for vessel size scoring."""
    return _score_vessel_size(vessel)


def _score_origin_and_repeat(vessel, opportunity) -> tuple[int, list[str]]:
    """Origin from Fujairah/Singapore (+8) and repeat caller (+5 for >=2 earlier
    observations in a target port within 90 days), capped at 13.
    """
    reasons = []
    points = 0

    # 1. Origin check
    came_from = False
    origin_name = "target port"

    opp_came_from = getattr(opportunity, "came_from_target_port", None)
    if opp_came_from:
        came_from = True
        val = str(opp_came_from).upper()
        if "AEFJR" in val or "FUJAIRAH" in val:
            origin_name = "Fujairah"
        elif "SGSIN" in val or "SINGAPORE" in val:
            origin_name = "Singapore"

    latest_obs = None
    if vessel.pk:
        latest_obs = vessel.observations.first()
        if latest_obs and getattr(latest_obs, "came_from_target_port", False):
            came_from = True
            lp = (latest_obs.last_port_unlocode or latest_obs.last_port or "").upper()
            if "AEFJR" in lp or "FUJAIRAH" in lp:
                origin_name = "Fujairah"
            elif "SGSIN" in lp or "SINGAPORE" in lp:
                origin_name = "Singapore"

    if came_from:
        origin_pts = SCORING_WEIGHTS["origin_target_port"]
        points += origin_pts
        reasons.append(f"came from {origin_name} {origin_pts}")

    # 2. Repeat caller check (>= 2 earlier observations in target port within 90 days)
    if vessel.pk:
        cutoff = timezone.now() - timedelta(days=SCORING_WEIGHTS["repeat_caller_window_days"])
        obs_qs = vessel.observations.filter(timestamp__gte=cutoff)
        if latest_obs and latest_obs.pk:
            obs_qs = obs_qs.exclude(pk=latest_obs.pk)

        earlier_count = 0
        for obs in obs_qs:
            cp = (obs.current_port or "").upper()
            dest = (obs.destination or "").upper()
            unlocode = (obs.next_port_unlocode or "").upper()
            if (
                any(tp in cp for tp in TARGET_PORT_NAMES)
                or any(tp in cp for tp in TARGET_PORT_UNLOCODES)
                or unlocode in TARGET_PORT_UNLOCODES
                or any(tp in dest for tp in TARGET_PORT_NAMES)
                or getattr(obs, "is_target_port", True)
            ):
                earlier_count += 1

        if earlier_count >= SCORING_WEIGHTS["repeat_caller_min_obs"]:
            repeat_pts = SCORING_WEIGHTS["repeat_caller"]
            points += repeat_pts
            reasons.append(f"repeat caller {repeat_pts}")

    capped_points = min(points, SCORING_WEIGHTS["origin_repeat_cap"])
    return capped_points, reasons


def _manager_points(company) -> tuple[int, str]:
    """Points and wording for a manager company, from the contact data we hold."""
    has_website = bool((company.website or "").strip())
    has_email = bool((company.email or "").strip())
    cfg = SCORING_WEIGHTS["manager_contacts"]
    if has_website and has_email:
        return cfg["website_and_email"], "with contacts"
    if has_website or has_email:
        return cfg["website_or_email"], "with partial contacts"
    return cfg["name_only"], "name only"


def _owner_points(company) -> tuple[int, str]:
    """Points and wording for an owner company."""
    cfg = SCORING_WEIGHTS["owner_contacts"]
    if (company.email or "").strip():
        return cfg["email"], "with email"
    return cfg["name_only"], "name only"


def _score_contacts(vessel) -> tuple[int, list[str]]:
    """Manager and owner contact quality (replaces the old "high priority
    manager only" rule, which gave nothing to enriched companies).

    - Manager: the best current relationship with role technical manager, ISM
      manager, commercial manager, operator or manager counts (20 with website
      and email, 12 with one of them, 6 with the name only). Not summed.
    - Owner: the best current registered or beneficial owner (8 with email,
      4 name only).
    - +5 when any of those companies was set to priority "high" by a person.
    - The three parts together are capped (``contacts_group_cap``).
    - No current relationships: 0 and no reason text.
    """
    if not vessel.pk:
        return 0, []

    relationships = list(
        vessel.relationships
        .filter(is_current=True, role__in=MANAGER_ROLES | OWNER_ROLES)
        .select_related("company")
    )
    if not relationships:
        return 0, []

    best_manager = None  # (points, preference_rank, role, wording)
    best_owner = None
    has_high_priority = False

    for rel in relationships:
        company = rel.company
        if company.priority == PRIORITY_HIGH:
            has_high_priority = True

        if rel.role in MANAGER_ROLES:
            pts, wording = _manager_points(company)
            rank = _MANAGER_ROLE_PREFERENCE.index(rel.role)
            candidate = (pts, -rank, rel.role, wording)
            if best_manager is None or candidate[:2] > best_manager[:2]:
                best_manager = candidate
        else:
            pts, wording = _owner_points(company)
            candidate = (pts, -_OWNER_ROLE_PREFERENCE.index(rel.role), rel.role, wording)
            if best_owner is None or candidate[:2] > best_owner[:2]:
                best_owner = candidate

    total = 0
    reasons: list[str] = []

    if best_manager:
        pts, _, role, wording = best_manager
        total += pts
        reasons.append(f"{role.replace('_', ' ')} {wording} {pts}")
    if best_owner:
        pts, _, role, wording = best_owner
        total += pts
        reasons.append(f"{role.replace('_', ' ')} {wording} {pts}")
    if has_high_priority:
        bonus = SCORING_WEIGHTS["priority_high_bonus"]
        total += bonus
        reasons.append(f"high-priority company {bonus}")

    cap = SCORING_WEIGHTS["contacts_group_cap"]
    if total > cap:
        reasons.append(f"contacts capped at {cap}")
        total = cap
    return total, reasons


def _score_vessel_segment(vessel) -> int:
    """Relevant vessel segment: +20 for exact match, +10 for keyword match."""
    vessel_type = vessel.vessel_type or ""
    if not vessel_type:
        return 0

    segments = getattr(settings, "SCORING_RELEVANT_VESSEL_SEGMENTS", {})

    exact_types = [t.lower() for t in segments.get("exact", [])]
    if vessel_type.lower() in exact_types:
        return SCORING_WEIGHTS["vessel_segment_exact"]

    vt_lower = vessel_type.lower()
    for keyword in segments.get("keyword", []):
        if keyword.lower() in vt_lower:
            return SCORING_WEIGHTS["vessel_segment_keyword"]

    return 0


def _score_existing_relationship(vessel, current_opportunity) -> int:
    """Existing relationship: +30 if a company linked to this vessel has a
    prior won Opportunity, +20 if a prior active-pipeline Opportunity exists."""
    from apps.opportunities.models import Opportunity
    from apps.relationships.models import VesselRelationship

    if not vessel.pk:
        return 0

    company_ids = vessel.relationships.values_list("company_id", flat=True)
    if not company_ids:
        return 0

    related_vessel_ids = (
        VesselRelationship.objects
        .filter(company_id__in=company_ids)
        .values_list("vessel_id", flat=True)
    )

    prior_opps = (
        Opportunity.objects
        .filter(vessel_id__in=related_vessel_ids)
    )
    if current_opportunity and current_opportunity.pk:
        prior_opps = prior_opps.exclude(pk=current_opportunity.pk)

    if prior_opps.filter(stage=STAGE_WON).exists():
        return SCORING_WEIGHTS["existing_relationship_won"]
    if prior_opps.filter(stage__in=_ACTIVE_PIPELINE_STAGES).exists():
        return SCORING_WEIGHTS["existing_relationship_pipeline"]
    return 0


def _score_verified_contact(vessel) -> int:
    """Verified decision-maker contact: +20 if any VesselRelationship for
    this vessel has verified=True."""
    if not vessel.pk:
        return 0
    has_verified = vessel.relationships.filter(verified=True).exists()
    return SCORING_WEIGHTS["verified_contact"] if has_verified else 0


def _score_previous_enquiry(vessel, current_opportunity) -> int:
    """Previous enquiry / quote: +25 if the vessel or its companies have a
    prior Opportunity that reached quote_requested or beyond."""
    from apps.opportunities.models import Opportunity
    from apps.relationships.models import VesselRelationship

    if not vessel.pk:
        return 0

    prior_vessel = (
        Opportunity.objects
        .filter(vessel=vessel, stage__in=_QUOTE_OR_BEYOND_STAGES)
    )
    if current_opportunity and current_opportunity.pk:
        prior_vessel = prior_vessel.exclude(pk=current_opportunity.pk)

    if prior_vessel.exists():
        return SCORING_WEIGHTS["previous_enquiry"]

    company_ids = vessel.relationships.values_list("company_id", flat=True)
    if company_ids:
        related_vessel_ids = (
            VesselRelationship.objects
            .filter(company_id__in=company_ids)
            .values_list("vessel_id", flat=True)
        )
        prior_company = (
            Opportunity.objects
            .filter(vessel_id__in=related_vessel_ids, stage__in=_QUOTE_OR_BEYOND_STAGES)
        )
        if current_opportunity and current_opportunity.pk:
            prior_company = prior_company.exclude(pk=current_opportunity.pk)

        if prior_company.exists():
            return SCORING_WEIGHTS["previous_enquiry"]

    return 0


def _score_recent_negative(vessel, current_opportunity) -> int:
    """Recent negative / closed interaction: -20 if the vessel or its
    companies have an Opportunity with stage='lost' in the configured window."""
    from apps.opportunities.models import Opportunity
    from apps.relationships.models import VesselRelationship

    if not vessel.pk:
        return 0

    window_days = getattr(
        settings,
        "SCORING_RECENT_NEGATIVE_WINDOW_DAYS",
        SCORING_WEIGHTS["recent_negative_window_days"],
    )
    cutoff = timezone.now() - timedelta(days=window_days)

    vessel_lost = (
        Opportunity.objects
        .filter(vessel=vessel, stage=STAGE_LOST, updated_at__gte=cutoff)
    )
    if current_opportunity and current_opportunity.pk:
        vessel_lost = vessel_lost.exclude(pk=current_opportunity.pk)

    if vessel_lost.exists():
        return SCORING_WEIGHTS["recent_negative"]

    company_ids = vessel.relationships.values_list("company_id", flat=True)
    if company_ids:
        related_vessel_ids = (
            VesselRelationship.objects
            .filter(company_id__in=company_ids)
            .values_list("vessel_id", flat=True)
        )
        company_lost = (
            Opportunity.objects
            .filter(vessel_id__in=related_vessel_ids, stage=STAGE_LOST, updated_at__gte=cutoff)
        )
        if current_opportunity and current_opportunity.pk:
            company_lost = company_lost.exclude(pk=current_opportunity.pk)

        if company_lost.exists():
            return SCORING_WEIGHTS["recent_negative"]

    return 0


# ---------------------------------------------------------------------------
# Main scoring functions
# ---------------------------------------------------------------------------

def calculate_score_and_reason(opportunity) -> tuple[int, str]:
    """Compute score clamped to [0, 100] and human-readable lead_reason."""
    vessel = opportunity.vessel
    reasons = []
    raw_score = 0

    # 1. Zone proximity
    zone_pts = _score_eta_zone(opportunity)
    raw_score += zone_pts
    zone = getattr(opportunity, "zone", "")
    if zone == ZONE_ANCHORAGE:
        reasons.append(f"Anchorage {zone_pts}")
    elif zone == ZONE_ANCHORAGE_BOUND:
        reasons.append(f"Anchorage bound {zone_pts}")
    elif zone == "in_port":
        reasons.append(f"In port {zone_pts}")
    elif zone_pts > 0:
        reasons.append(f"Inbound {zone_pts}")

    # 2. Vessel size from GRT
    size_pts = _score_vessel_size(vessel)
    raw_score += size_pts
    if vessel.grt is None:
        reasons.append("size unknown")
    elif size_pts > 0:
        reasons.append(f"size {size_pts}")

    # 3. Origin & repeat caller
    origin_pts, origin_reasons = _score_origin_and_repeat(vessel, opportunity)
    raw_score += origin_pts
    reasons.extend(origin_reasons)

    # 4. Manager and owner contact quality
    contact_pts, contact_reasons = _score_contacts(vessel)
    raw_score += contact_pts
    reasons.extend(contact_reasons)

    # 5. Vessel segment
    seg_pts = _score_vessel_segment(vessel)
    raw_score += seg_pts
    if seg_pts > 0:
        reasons.append(f"segment {seg_pts}")

    # 6. Existing relationship
    rel_pts = _score_existing_relationship(vessel, opportunity)
    raw_score += rel_pts
    if rel_pts > 0:
        reasons.append(f"existing relationship {rel_pts}")

    # 7. Verified decision-maker contact
    ver_pts = _score_verified_contact(vessel)
    raw_score += ver_pts
    if ver_pts > 0:
        reasons.append(f"verified contact {ver_pts}")

    # 8. Previous enquiry / quote
    enq_pts = _score_previous_enquiry(vessel, opportunity)
    raw_score += enq_pts
    if enq_pts > 0:
        reasons.append(f"previous enquiry {enq_pts}")

    # 9. Recent negative interaction
    neg_pts = _score_recent_negative(vessel, opportunity)
    raw_score += neg_pts
    if neg_pts < 0:
        reasons.append(f"recent lost {neg_pts}")

    score = max(min(raw_score, SCORING_WEIGHTS["score_max"]), SCORING_WEIGHTS["score_min"])
    reason_str = ", ".join(reasons)[:200]
    return score, reason_str


def calculate_score(opportunity) -> int:
    """Compute the lead score for an Opportunity by summing all applicable
    signal scores. Returns an integer clamped between 0 and 100."""
    score, _ = calculate_score_and_reason(opportunity)
    return score
