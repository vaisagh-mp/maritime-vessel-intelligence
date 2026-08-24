"""Pure parsing functions for DataDocked response bodies — no HTTP, no ORM."""
import logging
from datetime import datetime, timezone as dt_timezone

logger = logging.getLogger("vessel_intel")


def parse_vessels_by_area(payload: dict) -> list:
    """Returns the list of raw vessel dicts from a get-vessels-by-area response."""
    return payload.get("vessels", []) or []


def parse_eta_utc(eta_utc_str: str):
    """Parses DataDocked's `"Aug 09, 2026 05:51 UTC"` format into an aware
    datetime, or None if missing/unparseable."""
    if not eta_utc_str:
        return None
    cleaned = eta_utc_str.replace(" UTC", "").strip()
    try:
        naive = datetime.strptime(cleaned, "%b %d, %Y %H:%M")
    except ValueError:
        return None
    return naive.replace(tzinfo=dt_timezone.utc)


def parse_location_response(payload: dict) -> dict:
    return {
        "imo": payload.get("imo"),
        "mmsi": payload.get("mmsi"),
        "name": payload.get("name"),
        "eta": parse_eta_utc(payload.get("etaUtc")),
        "destination": payload.get("destination"),
        "latitude": _to_float(payload.get("latitude")),
        "longitude": _to_float(payload.get("longitude")),
        "navigational_status": payload.get("navigationalStatus"),
    }


def parse_management_response(payload: dict) -> dict:
    management = payload.get("management") or {}

    def clean(value):
        # DataDocked uses "-" as a null placeholder for unavailable fields.
        if value is None or str(value).strip() in ("", "-"):
            return None
        return value

    return {
        "imo": payload.get("imo"),
        "mmsi": payload.get("mmsi"),
        "manager_name": clean(management.get("manager")),
        "manager_email": clean(management.get("managerEmail") or management.get("ismEmail")),
        "manager_website": clean(management.get("managerWebsite")),
        "manager_address": clean(management.get("managerAddress")),
        "registered_owner_name": clean(management.get("registeredOwner")),
        "registered_owner_email": clean(management.get("registeredOwnerEmail")),
        "registered_owner_website": clean(management.get("registeredOwnerWebsite")),
        "registered_owner_address": clean(management.get("registeredOwnerAddress")),
    }


def parse_expected_arrivals_response(payload: dict) -> tuple:
    """Parses a port-calls-by-port?search_type=expected response.

    Returns ``(meta, items)`` where:
      - ``meta`` is ``{"total": int, "pages": int}``
      - ``items`` is a list of normalised vessel dicts ready for the task layer

    MMSI is an integer in this response; we cast it to str for consistency
    with ``Vessel.mmsi`` throughout the rest of the system.

    ``formattedETA`` is parsed defensively:
      1. Try the known ``"Aug 09, 2026 05:51 UTC"`` format via ``parse_eta_utc``.
      2. Fall back to ``dateutil.parser.parse`` (timezone-aware when possible).
      3. On any failure log a warning with the raw string and set ``eta=None`` —
         one bad record never aborts the whole batch.
    """
    expected = (payload.get("detail") or {}).get("expected") or {}
    meta = {
        "total": expected.get("total", 0),
        "pages": expected.get("pages", 1),
    }
    raw_list = expected.get("list") or []

    items = []
    for raw in raw_list:
        mmsi_raw = raw.get("mmsi")
        mmsi = str(mmsi_raw) if mmsi_raw is not None else None

        eta = _parse_formatted_eta(raw.get("formattedETA"))

        items.append({
            "mmsi": mmsi,
            "name": raw.get("name"),
            "imo": raw.get("imo"),
            "type": raw.get("type"),
            "year": raw.get("year"),
            "country": raw.get("country"),
            "gt": raw.get("gt"),
            "dw": raw.get("dw"),
            "sizes": raw.get("sizes"),
            "eta": eta,
        })

    return meta, items


def _parse_formatted_eta(formatted_eta_str):
    """Defensive multi-strategy ETA parser for the ``formattedETA`` field.
    Returns an aware datetime or None; never raises."""
    if not formatted_eta_str:
        return None

    # Strategy 1: known primary format "Aug 09, 2026 05:51 UTC"
    parsed = parse_eta_utc(formatted_eta_str)
    if parsed is not None:
        return parsed

    # Strategy 2: dateutil — handles a broad range of ISO/RFC formats
    try:
        from dateutil import parser as dateutil_parser
        from dateutil.parser import ParserError
        dt = dateutil_parser.parse(formatted_eta_str)
        # Ensure tz-aware; treat naive as UTC
        if dt.tzinfo is None:
            from datetime import timezone as dt_timezone
            dt = dt.replace(tzinfo=dt_timezone.utc)
        return dt
    except Exception:
        pass

    # Strategy 3: give up gracefully — don't crash the batch
    logger.warning(
        "Expected-arrivals: could not parse formattedETA %r — treating eta as None",
        formatted_eta_str,
    )
    return None


def _to_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
