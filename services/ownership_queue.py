"""
services/ownership_queue.py

Which vessels get an owner and manager lookup first.

Only a few lookups are available each day, so they go to the leads that matter most:
due within 24 hours first, then 72 hours, then anchorage-bound, then at anchor; inside
each group the highest score, then the largest vessel. A vessel appears once.
"""
from datetime import timedelta
from typing import List, Optional

from django.conf import settings
from django.db.models import Case, F, IntegerField, Q, Value, When
from django.utils import timezone

from apps.common.constants import (
    CLOSED_STAGES,
    STALE_INBOUND_HIDE_HOURS,
    ZONE_24H,
    ZONE_72H,
    ZONE_ANCHORAGE,
    ZONE_ANCHORAGE_BOUND,
)
from apps.opportunities.models import Opportunity


def recheck_days() -> int:
    return max(1, int(getattr(settings, "OWNERSHIP_RECHECK_DAYS", 180)))


def lowest_score_worth_a_lookup() -> int:
    """The MEDIUM threshold: LOW leads are never looked up automatically."""
    for threshold, label in settings.SCORE_BANDS:
        if label == "MEDIUM":
            return threshold
    return 0


def ownership_queue(limit: int, port_code: Optional[str] = None, now=None) -> List[str]:
    """IMOs to look up, best first. Empty when there is nothing worth looking up."""
    if limit <= 0:
        return []
    now = now or timezone.now()
    recheck_cutoff = now - timedelta(days=recheck_days())
    stale_cutoff = now - timedelta(hours=STALE_INBOUND_HIDE_HOURS)

    qs = (
        Opportunity.objects.filter(vessel__imo__isnull=False, score__gte=lowest_score_worth_a_lookup())
        .exclude(stage__in=CLOSED_STAGES)
        .exclude(is_inbound=True, eta__lt=stale_cutoff)
        .filter(Q(vessel__ownership_checked_at__isnull=True) | Q(vessel__ownership_checked_at__lt=recheck_cutoff))
    )
    if port_code:
        qs = qs.filter(port__un_locode=port_code)
    qs = qs.annotate(
        zone_rank=Case(
            When(zone=ZONE_24H, then=Value(0)),
            When(zone=ZONE_72H, then=Value(1)),
            When(zone=ZONE_ANCHORAGE_BOUND, then=Value(2)),
            When(zone=ZONE_ANCHORAGE, then=Value(3)),
            default=Value(4),
            output_field=IntegerField(),
        )
    ).order_by("zone_rank", "-score", F("vessel__grt").desc(nulls_last=True), "id")

    seen, imos = set(), []
    for imo in qs.values_list("vessel__imo", flat=True).iterator():
        if imo and len(imo) == 7 and imo.isdigit() and imo not in seen:
            seen.add(imo)
            imos.append(imo)
            if len(imos) >= limit:
                break
    return imos
