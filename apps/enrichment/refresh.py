"""
Live refresh from the web app: one MarineTraffic Expected Arrivals call for one
port, started by a button on the Lead board.

This module deliberately re-uses the existing ``ingest_expected_arrivals``
management command (same fetch, parse, save, score and EnrichmentLog code), so
the button and the command can never drift apart.

Safety rules enforced here:
  * a 120 second cooldown shared by all users and ports, claimed with ONE
    conditional UPDATE (race-safe on PostgreSQL and SQLite);
  * only one run at a time;
  * API keys never leave the server: every message is passed through
    ``sanitize`` and only a short text is stored or returned;
  * no automatic retry on provider errors.
"""
import logging
import math
import re
import threading
from datetime import timedelta
from io import StringIO
from typing import Any, Dict, Optional, Tuple

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.db.models import Q
from django.utils import timezone

from apps.ports.models import Port

from .models import IngestRun, ProviderCallState

logger = logging.getLogger("vessel_intel")

PROVIDER = "marinetraffic"
MODE = "arrivals"
MAX_ERROR_CHARS = 300

_SUMMARY_PATTERNS = {
    "raw_rows": r"Raw rows: (\d+)",
    "accepted": r"Accepted: (\d+)",
    "rejected": r"Rejected: (\d+)",
    "excluded_by_filter": r"Excluded by vessel filter: (\d+)",
    "vessels_created": r"Vessels created: (\d+)",
    "vessels_updated": r"Vessels updated: (\d+)",
    "observations_created": r"Observations created: (\d+)",
    "opportunities_created": r"Opportunities created: (\d+)",
    "opportunities_updated": r"Opportunities created: \d+, updated: (\d+)",
    "opportunities_skipped": r"Opportunities created: \d+, updated: \d+, skipped: (\d+)",
    "errors": r"Errors: (\d+)",
}


_AIS_PATTERNS = {
    "ais_features": r"AIS features: (\d+)",
    "ais_accepted": r"Accepted: (\d+)",
    "ais_in_anchorage": r"In anchorage: (\d+)",
    "ais_moored": r"Moored in port: (\d+)",
    "ais_moving": r"Moving in area: (\d+)",
    "ais_vessels_created": r"Vessels created: (\d+)",
    "ais_observations_created": r"Observations created: (\d+)",
    "ais_opportunities_created": r"Opportunities created: (\d+)",
    "ais_opportunities_updated": r"Opportunities created: \d+, updated: (\d+)",
    "ais_errors": r"Errors: (\d+)",
}


_OWNERSHIP_PATTERNS = {
    "own_requested": r"IMOs requested\s*: (\d+)",
    "own_vessels_updated": r"Vessels updated\s*: (\d+)",
    "own_companies_created": r"Companies created\s*: (\d+)",
    "own_relationships_created": r"Relationships created\s*: (\d+)",
    "own_rescored": r"Leads rescored\s*: (\d+)",
    "own_errors": r"Errors\s*: (\d+)",
}

OWNERSHIP_REFRESH_DAYS = 30


def sanitize(text: Any) -> str:
    """Remove any configured provider key from a message."""
    clean = re.sub(r"\x1b\[[0-9;]*m", "", str(text))  # terminal colour codes
    for name in ("MARINETRAFFIC_API_KEY", "KPLER_API_KEY"):
        key = getattr(settings, name, "") or ""
        if key and key in clean:
            clean = clean.replace(key, "{api_key}")
    return clean


def parse_ais_report(text: str) -> Dict[str, int]:
    """Read the numbers out of the ingest_ais_latest report."""
    summary: Dict[str, int] = {}
    for name, pattern in _AIS_PATTERNS.items():
        match = re.search(pattern, text)
        if match:
            summary[name] = int(match.group(1))
    return summary


def parse_ownership_report(text: str) -> Dict[str, int]:
    """Read the numbers out of the enrich_ownership live report."""
    summary: Dict[str, int] = {}
    for name, pattern in _OWNERSHIP_PATTERNS.items():
        match = re.search(pattern, text)
        if match:
            summary[name] = int(match.group(1))
    return summary


def parse_report(text: str) -> Dict[str, int]:
    """Read the numbers out of the command's printed report."""
    summary: Dict[str, int] = {}
    for name, pattern in _SUMMARY_PATTERNS.items():
        match = re.search(pattern, text)
        if match:
            summary[name] = int(match.group(1))
    return summary


# --------------------------------------------------------------------------
# Cooldown
# --------------------------------------------------------------------------

def cooldown_seconds() -> int:
    return int(getattr(settings, "INGEST_REFRESH_COOLDOWN_SECONDS", 120))


def cooldown_remaining(now=None) -> int:
    """Whole seconds still to wait (rounded up), 0 when a call is allowed."""
    now = now or timezone.now()
    state = ProviderCallState.objects.filter(provider=PROVIDER).first()
    if not state or not state.last_call_at:
        return 0
    elapsed = (now - state.last_call_at).total_seconds()
    return max(0, int(math.ceil(cooldown_seconds() - elapsed)))


def claim_cooldown(now=None) -> bool:
    """Atomically take the next call slot. True = you may call the provider."""
    now = now or timezone.now()
    ProviderCallState.objects.get_or_create(provider=PROVIDER)
    cutoff = now - timedelta(seconds=cooldown_seconds())
    claimed = (
        ProviderCallState.objects.filter(provider=PROVIDER)
        .filter(Q(last_call_at__isnull=True) | Q(last_call_at__lte=cutoff))
        .update(last_call_at=now)
    )
    return claimed == 1


# --------------------------------------------------------------------------
# Runs
# --------------------------------------------------------------------------

def expire_stale_runs(now=None) -> int:
    """A run stuck in 'running' (crashed worker) must never block the button."""
    now = now or timezone.now()
    minutes = int(getattr(settings, "INGEST_REFRESH_STALE_MINUTES", 10))
    cutoff = now - timedelta(minutes=minutes)
    return IngestRun.objects.filter(
        status=IngestRun.STATUS_RUNNING, started_at__lte=cutoff
    ).update(
        status=IngestRun.STATUS_FAILED,
        finished_at=now,
        error="Timed out. The refresh did not finish.",
    )


def serialize_run(run: Optional[IngestRun]) -> Optional[Dict[str, Any]]:
    if run is None:
        return None
    return {
        "run_id": run.pk,
        "port": run.port_code,
        "mode": run.mode,
        "status": run.status,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "summary": run.summary or {},
        "error": run.error,
        "requested_by": run.requested_by.get_username() if run.requested_by_id else "",
    }


def status_payload() -> Dict[str, Any]:
    expire_stale_runs()
    running = IngestRun.objects.filter(status=IngestRun.STATUS_RUNNING).first()
    last = IngestRun.objects.exclude(status=IngestRun.STATUS_RUNNING).first()
    return {
        "enabled": bool(getattr(settings, "INGEST_REFRESH_ENABLED", True)),
        "cooldown_seconds": cooldown_seconds(),
        "cooldown_remaining": cooldown_remaining(),
        "running": serialize_run(running),
        "last_run": serialize_run(last),
        "ownership": ownership_status_payload(),
        "arrivals": arrivals_status_payload(),
    }


def ownership_status_payload() -> Dict[str, Any]:
    from services import quota_service

    st = quota_service.ownership_status()
    st["enabled"] = bool(getattr(settings, "KPLER_OWNERSHIP_ENABLED", False))
    st["recheck_days"] = int(getattr(settings, "OWNERSHIP_RECHECK_DAYS", 180))
    return st


def arrivals_status_payload() -> list:
    """Per port: when arrivals were last fetched and when the next call is allowed."""
    from services import quota_service

    rows = []
    for port in Port.objects.filter(active=True, marinetraffic_port_id__isnull=False).order_by("un_locode"):
        last = quota_service.arrivals_last_success(port.un_locode)
        nxt = quota_service.arrivals_next_allowed(port.un_locode)
        rows.append({
            "port": port.un_locode,
            "last_at": last.isoformat() if last else None,
            "next_allowed_at": nxt.isoformat() if nxt else None,
            "allowed_now": quota_service.arrivals_allowed(port.un_locode),
        })
    return rows


def manual_owner_lookup(user, vessel, force: bool = False) -> Tuple[int, Dict[str, Any]]:
    """The "Look up owner" button: one Kpler lookup for one vessel.

    Refused (with a plain reason) when the feature is off, the vessel has no valid
    IMO, it was checked inside the re-check period (Admin may force), the daily
    share for the button is used up, or the monthly allowance is spent.
    """
    from apps.common.permissions import is_admin
    from services import quota_service

    if not getattr(settings, "KPLER_OWNERSHIP_ENABLED", False):
        return 409, {"detail": "Owner lookup is switched off."}
    imo = vessel.imo or ""
    if not (len(imo) == 7 and imo.isdigit()):
        return 400, {"detail": "This vessel has no valid IMO number."}
    days = int(getattr(settings, "OWNERSHIP_RECHECK_DAYS", 180))
    if vessel.ownership_checked_at and not (force and is_admin(user)):
        if vessel.ownership_checked_at > timezone.now() - timedelta(days=days):
            return 409, {
                "detail": f"Already checked on {vessel.ownership_checked_at:%d %b %Y}. "
                          f"It can be checked again after {days} days (an Admin can force it).",
            }
    if quota_service.ownership_remaining() <= 0:
        return 429, {"detail": "The monthly owner lookup allowance is used up."}
    if quota_service.manual_left_today() <= 0:
        return 429, {"detail": "Today's manual owner lookups are used up. Try again tomorrow."}
    out, err = StringIO(), StringIO()
    try:
        call_command(
            "enrich_ownership", live=True, apply=True, imos=[imo], max_imos=1,
            pause_seconds=0, manual=True, stdout=out, stderr=err,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("Manual owner lookup failed for %s: %s", imo, sanitize(repr(exc)))
        return 502, {"detail": "Owner lookup failed. See the server log."}
    problem = err.getvalue().strip().splitlines()
    if problem:
        return 502, {"detail": sanitize(problem[0])[:MAX_ERROR_CHARS]}
    summary = parse_ownership_report(out.getvalue())
    vessel.refresh_from_db()
    return 200, {
        "detail": "Owner lookup finished.",
        "summary": summary,
        "checked_at": vessel.ownership_checked_at.isoformat() if vessel.ownership_checked_at else None,
        "ownership": ownership_status_payload(),
    }


def _run_ais_step(port_code: str, summary: Dict[str, Any]) -> None:
    """Second step of a refresh: AIS Latest for the same port. Never fails the run."""
    if not getattr(settings, "INGEST_REFRESH_AIS_ENABLED", True):
        return
    port = Port.objects.filter(un_locode=port_code).first()
    if port is None or not (port.ais_filter or "").strip():
        summary["ais_skipped"] = "no_area_filter"
        return
    out = StringIO()
    try:
        call_command(
            "ingest_ais_latest", live=True, ports=[port_code], stdout=out, stderr=StringIO()
        )
        summary.update(parse_ais_report(out.getvalue()))
    except CommandError as exc:
        summary["ais_error"] = sanitize(exc)[:MAX_ERROR_CHARS]
    except Exception as exc:  # noqa: BLE001
        summary["ais_error"] = "Unexpected AIS error. See the server log."
        logger.error("AIS step failed for %s: %s", port_code, sanitize(repr(exc)))


def ownership_candidates(port_code: str, limit: int) -> list:
    """IMOs on this port's leads to look up next, best first.

    Uses the shared priority queue (anchorage first, then score, then size; no LOW
    leads, no stale ETAs, nothing checked inside the re-check period).
    """
    from services.ownership_queue import ownership_queue

    return ownership_queue(limit, port_code=port_code)


def _run_ownership_step(port_code: str, summary: Dict[str, Any]) -> None:
    """Third step of a refresh: owners and managers from Kpler for this port's top leads.

    Off unless KPLER_OWNERSHIP_ENABLED is true. Capped per click and by the monthly
    IMO cap. Never fails the run.
    """
    if not getattr(settings, "INGEST_REFRESH_OWNERSHIP_ENABLED", True):
        return
    if not getattr(settings, "KPLER_OWNERSHIP_ENABLED", False):
        summary["own_skipped"] = "disabled"
        return
    from services import quota_service

    budget = quota_service.auto_budget_today()
    if budget <= 0:
        summary["own_skipped"] = "budget"
        return
    limit = max(1, min(int(getattr(settings, "INGEST_REFRESH_OWNERSHIP_MAX_IMOS", 20)), budget))
    imos = ownership_candidates(port_code, limit)
    if not imos:
        summary["own_skipped"] = "no_candidates"
        return
    out, err = StringIO(), StringIO()
    try:
        call_command(
            "enrich_ownership",
            live=True,
            apply=True,
            imos=imos,
            max_imos=len(imos),
            pause_seconds=0,
            stdout=out,
            stderr=err,
        )
    except Exception as exc:  # noqa: BLE001 - this step must never fail the run
        summary["own_error"] = "Unexpected owner lookup error. See the server log."
        logger.error("Ownership step failed for %s: %s", port_code, sanitize(repr(exc)))
        return
    report = out.getvalue()
    if "Monthly quota limit reached" in report:
        summary["own_skipped"] = "quota"
        return
    problem = err.getvalue().strip().splitlines()
    if problem:
        summary["own_error"] = sanitize(problem[0])[:MAX_ERROR_CHARS]
    summary.update(parse_ownership_report(report))


class _Done(Exception):
    """Internal: the run finished without calling MarineTraffic."""


def execute_run(run_id: int) -> None:
    """Do the live call for one run and record the outcome. Never raises."""
    run = IngestRun.objects.get(pk=run_id)
    out, err = StringIO(), StringIO()
    status, error, summary = IngestRun.STATUS_SUCCESS, "", {}
    try:
        from services import quota_service

        if not quota_service.arrivals_allowed(run.port_code):
            # MarineTraffic allows one extended call per port per day: do not spend it twice.
            last = quota_service.arrivals_last_success(run.port_code)
            nxt = quota_service.arrivals_next_allowed(run.port_code)
            summary = {
                "arrivals_skipped": True,
                "arrivals_last_at": last.isoformat() if last else None,
                "arrivals_next_at": nxt.isoformat() if nxt else None,
            }
            _run_ais_step(run.port_code, summary)
            _run_ownership_step(run.port_code, summary)
            raise _Done
        call_command(
            "ingest_expected_arrivals",
            mode=MODE,
            live=True,
            ports=[run.port_code],
            stdout=out,
            stderr=err,
        )
        summary = parse_report(out.getvalue())
        if not summary:
            status, error = IngestRun.STATUS_FAILED, "The port was not processed."
        else:
            _run_ais_step(run.port_code, summary)
            _run_ownership_step(run.port_code, summary)
    except _Done:
        pass
    except CommandError as exc:
        status = IngestRun.STATUS_FAILED
        error = sanitize(exc)[:MAX_ERROR_CHARS]
        summary = parse_report(out.getvalue())
    except Exception as exc:  # noqa: BLE001 - must never escape the thread
        status = IngestRun.STATUS_FAILED
        error = "Unexpected error. See the server log."
        logger.error("Live refresh failed for %s: %s", run.port_code, sanitize(repr(exc)))
    finally:
        run.status = status
        run.error = error
        run.summary = summary
        run.finished_at = timezone.now()
        run.save(update_fields=["status", "error", "summary", "finished_at"])


def _thread_target(run_id: int) -> None:
    try:
        execute_run(run_id)
    finally:
        connection.close()


def start_refresh(user, port_code: Any) -> Tuple[int, Dict[str, Any], Dict[str, str]]:
    """Validate, claim the cooldown, and start one live run.

    Returns (http_status, json_body, extra_headers).
    """
    if not getattr(settings, "INGEST_REFRESH_ENABLED", True):
        return 503, {"detail": "Live refresh is disabled.", "code": "disabled"}, {}

    code = str(port_code or "").strip().upper()
    if code not in getattr(settings, "INGEST_REFRESH_PORTS", []):
        return 400, {"detail": "Choose Singapore or Fujairah.", "code": "invalid_port"}, {}

    if not (getattr(settings, "MARINETRAFFIC_API_KEY", "") or "").strip():
        return 503, {
            "detail": "MarineTraffic is not configured on the server.",
            "code": "not_configured",
        }, {}

    if not Port.objects.filter(un_locode=code, marinetraffic_port_id__isnull=False).exists():
        return 400, {"detail": "That port is not set up for live data.", "code": "invalid_port"}, {}

    expire_stale_runs()
    running = IngestRun.objects.filter(status=IngestRun.STATUS_RUNNING).first()
    if running:
        return 409, {
            "detail": "A refresh is already running.",
            "code": "already_running",
            "run_id": running.pk,
        }, {}

    if not claim_cooldown():
        wait = max(1, cooldown_remaining())
        return 429, {
            "detail": "Please wait before the next live refresh.",
            "code": "cooldown",
            "retry_after_seconds": wait,
        }, {"Retry-After": str(wait)}

    run = IngestRun.objects.create(
        port_code=code,
        mode=MODE,
        status=IngestRun.STATUS_RUNNING,
        requested_by=user if getattr(user, "is_authenticated", False) else None,
    )

    if getattr(settings, "INGEST_REFRESH_SYNC", False):
        execute_run(run.pk)
    else:
        threading.Thread(target=_thread_target, args=(run.pk,), daemon=True).start()

    return 202, {
        "run_id": run.pk,
        "status": IngestRun.STATUS_RUNNING if not getattr(settings, "INGEST_REFRESH_SYNC", False)
        else IngestRun.objects.get(pk=run.pk).status,
        "cooldown_seconds": cooldown_seconds(),
    }, {}
