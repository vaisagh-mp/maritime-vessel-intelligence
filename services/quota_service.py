"""
services/quota_service.py

Counting what the data providers allow us, so no step makes a call that will fail.

* MarineTraffic extended arrivals: one call per port per day.
  Every live arrivals call is already written to EnrichmentLog.
* Kpler owner and manager lookups: a monthly allowance of vessels (IMOs).
  A lookup is recorded on Vessel.ownership_checked_at, and each live batch is
  also written to EnrichmentLog so it can be audited.

Pure counting. This module never calls a provider.
"""
import calendar
import math
from datetime import date, datetime, timedelta, timezone as dt_timezone
from typing import Any, Dict, Optional

from django.conf import settings
from django.db.models import Sum
from django.utils import timezone

from apps.enrichment.models import EnrichmentLog
from apps.vessels.models import Vessel

ARRIVALS_ENDPOINT = "marinetraffic:expected_arrivals"
OWNERSHIP_ENDPOINT = "kpler:ownership"
OWNERSHIP_MANUAL_ENDPOINT = "kpler:ownership:manual"


def _utc(now: Optional[datetime]) -> datetime:
    return (now or timezone.now()).astimezone(dt_timezone.utc)


# --------------------------------------------------------------------------
# MarineTraffic arrivals (one call per port per day)
# --------------------------------------------------------------------------

def arrivals_last_success(port_code: str) -> Optional[datetime]:
    """When the last successful live arrivals call for this port finished, or None."""
    row = (
        EnrichmentLog.objects.filter(
            endpoint_called=ARRIVALS_ENDPOINT, success=True, port__un_locode=port_code
        )
        .order_by("-timestamp")
        .first()
    )
    return row.timestamp if row else None


def arrivals_next_allowed(port_code: str) -> Optional[datetime]:
    """When this port may be fetched again, or None when it may be fetched now."""
    last = arrivals_last_success(port_code)
    if last is None:
        return None
    gap = timedelta(hours=int(getattr(settings, "MT_ARRIVALS_MIN_GAP_HOURS", 23)))
    nxt = last + gap
    return nxt if nxt > timezone.now() else None


def arrivals_allowed(port_code: str) -> bool:
    return arrivals_next_allowed(port_code) is None


# --------------------------------------------------------------------------
# Kpler owner and manager lookups (monthly allowance)
# --------------------------------------------------------------------------

def _shift_month(year: int, month: int, delta: int):
    index = year * 12 + (month - 1) + delta
    return index // 12, index % 12 + 1


def _reset_date(year: int, month: int, reset_day: int) -> date:
    return date(year, month, min(reset_day, calendar.monthrange(year, month)[1]))


def period_bounds(now: Optional[datetime] = None) -> Dict[str, Any]:
    """The current allowance period: start, end, length in days and today's day number."""
    n = _utc(now)
    reset_day = min(max(int(getattr(settings, "KPLER_QUOTA_RESET_DAY", 1)), 1), 28)
    today = n.date()
    if today.day >= reset_day:
        sy, sm = today.year, today.month
    else:
        sy, sm = _shift_month(today.year, today.month, -1)
    ey, em = _shift_month(sy, sm, 1)
    start = _reset_date(sy, sm, reset_day)
    end = _reset_date(ey, em, reset_day)
    return {
        "start": datetime(start.year, start.month, start.day, tzinfo=dt_timezone.utc),
        "end": datetime(end.year, end.month, end.day, tzinfo=dt_timezone.utc),
        "days": (end - start).days,
        "day_number": (today - start).days + 1,
    }


def ownership_cap() -> int:
    return max(0, int(getattr(settings, "KPLER_OWNERSHIP_MONTHLY_IMO_CAP", 480)))


def ownership_used(now: Optional[datetime] = None) -> int:
    """Vessels looked up in the current period."""
    p = period_bounds(now)
    return Vessel.objects.filter(
        ownership_checked_at__gte=p["start"], ownership_checked_at__lt=p["end"]
    ).count()


def ownership_remaining(now: Optional[datetime] = None) -> int:
    return max(0, ownership_cap() - ownership_used(now))


def _lookups_logged_today(endpoint: str, now: Optional[datetime]) -> int:
    n = _utc(now)
    midnight = datetime(n.year, n.month, n.day, tzinfo=dt_timezone.utc)
    total = EnrichmentLog.objects.filter(
        endpoint_called=endpoint, success=True, timestamp__gte=midnight
    ).aggregate(total=Sum("credits_spent"))["total"]
    return int(total or 0)


def manual_reserve() -> int:
    return max(0, int(getattr(settings, "OWNERSHIP_MANUAL_DAILY_RESERVE", 4)))


def manual_used_today(now: Optional[datetime] = None) -> int:
    return _lookups_logged_today(OWNERSHIP_MANUAL_ENDPOINT, now)


def manual_left_today(now: Optional[datetime] = None) -> int:
    """Lookups the button may still make today."""
    return max(0, min(manual_reserve() - manual_used_today(now), ownership_remaining(now)))


def pace_pool_today(now: Optional[datetime] = None) -> int:
    """How many lookups may still be made today to spread the allowance evenly.

    The allowance is released day by day: on day N of D the total used may reach
    ceil(cap * N / D). Anything not used carries over, anything borrowed is paid back.
    """
    p = period_bounds(now)
    cap = ownership_cap()
    target = int(math.ceil(cap * p["day_number"] / p["days"]))
    return max(0, min(target - ownership_used(now), ownership_remaining(now)))


def daily_max() -> int:
    """Ceiling for automatic lookups in one UTC day, so catching up is gradual."""
    return max(0, int(getattr(settings, "OWNERSHIP_DAILY_MAX_IMOS", 32)))


def checked_today(now: Optional[datetime] = None) -> int:
    """Vessels whose owner lookup was recorded since UTC midnight (manual or automatic)."""
    now = now or timezone.now()
    midnight = now.astimezone(dt_timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    return Vessel.objects.filter(ownership_checked_at__gte=midnight).count()


def auto_budget_today(now: Optional[datetime] = None) -> int:
    """Lookups the daily sync / Refresh button may still make today.

    Even pace with carry-over, minus the share kept for the button, and never more
    than OWNERSHIP_DAILY_MAX_IMOS automatic lookups in one day.
    """
    reserve_left = max(0, manual_reserve() - manual_used_today(now))
    paced = max(0, pace_pool_today(now) - reserve_left)
    auto_done_today = max(0, checked_today(now) - manual_used_today(now))
    return max(0, min(paced, daily_max() - auto_done_today))


def ownership_status(now: Optional[datetime] = None) -> Dict[str, Any]:
    p = period_bounds(now)
    return {
        "cap": ownership_cap(),
        "used": ownership_used(now),
        "remaining": ownership_remaining(now),
        "period_start": p["start"].date().isoformat(),
        "period_end": p["end"].date().isoformat(),
        "auto_budget_today": auto_budget_today(now),
        "manual_left_today": manual_left_today(now),
        "manual_reserve": manual_reserve(),
    }
