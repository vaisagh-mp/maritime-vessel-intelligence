"""
integrations/kpler/arrivals_parser.py

Pure-Python parser and cleaning module for MarineTraffic / Kpler Expected Arrivals data.
Standard library only: does not import Django, ORM models, requests, or anything from
apps/ or services/.
"""

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence


@dataclass
class ParseResult:
    """Result of parsing expected arrivals rows."""

    accepted: List[Dict[str, Any]]
    rejected: List[Dict[str, Any]]
    stats: Dict[str, Any]


def _parse_float(val: Any, allow_zero: bool = True) -> Optional[float]:
    """Safely convert value to float, returning None on invalid/empty/missing input."""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        f = float(val)
        if not allow_zero and f == 0.0:
            return None
        return f
    s = str(val).strip()
    if not s:
        return None
    try:
        f = float(s)
        if not allow_zero and f == 0.0:
            return None
        return f
    except (ValueError, TypeError):
        return None


def _parse_int(val: Any, allow_zero: bool = True) -> Optional[int]:
    """Safely convert value to int, returning None on invalid/empty/missing input."""
    if val is None:
        return None
    if isinstance(val, int):
        if not allow_zero and val == 0:
            return None
        return val
    s = str(val).strip()
    if not s:
        return None
    try:
        # Accepts float string representations like '2020.0' or direct integer strings
        f = float(s)
        i = int(f)
        if not allow_zero and i == 0:
            return None
        return i
    except (ValueError, TypeError):
        return None


def _parse_datetime_utc(val: Any) -> Optional[datetime]:
    """Parse UTC datetime formatted as %Y-%m-%dT%H:%M:%S into timezone-aware UTC datetime."""
    if val is None:
        return None
    if isinstance(val, datetime):
        if val.tzinfo is None:
            return val.replace(tzinfo=timezone.utc)
        return val.astimezone(timezone.utc)
    s = str(val).strip()
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                return dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except (ValueError, TypeError):
            return None


def parse_arrivals(
    rows: Sequence[Dict[str, Any]],
    *,
    port: Dict[str, Any],
    snapshot: Optional[datetime] = None,
    window_days: int = 14,
    other_ports: Sequence[Dict[str, Any]] = (),
) -> ParseResult:
    """
    Parse and clean raw expected arrivals rows into provider-agnostic records.

    Input rows are never mutated.

    Args:
        rows: Sequence of raw dicts returned by fetch_expected_arrivals.
        port: Dict describing the queried port, e.g.:
              {"port_id": "290", "unlocode": "SGSIN", "home_names": ["SINGAPORE"]}
        snapshot: Reference datetime for staleness and ETA calculations. Defaults to the
                  maximum TIMESTAMP among all input rows.
        window_days: Number of days ahead for ETA window checks (default: 14).
        other_ports: Sequence of dicts describing other ports for target tracking.

    Returns:
        ParseResult containing accepted records, rejected records with reasons, and summary stats.
    """
    if not rows:
        return ParseResult(
            accepted=[],
            rejected=[],
            stats={
                "raw_rows": 0,
                "accepted": 0,
                "rejected": 0,
                "invalid_imo": 0,
                "invalid_mmsi": 0,
                "no_position": 0,
                "stale_position": 0,
                "duplicate": 0,
                "rejection_reasons": {
                    "invalid_imo": 0,
                    "invalid_mmsi": 0,
                    "no_position": 0,
                    "stale_position": 0,
                    "duplicate": 0,
                },
                "port_areas": {
                    "inbound": 0,
                    "in_port": 0,
                    "anchorage": 0,
                    "anchorage_bound": 0,
                    "unknown": 0,
                },
                "flag_counts": {},
                "snapshot": snapshot.isoformat() if snapshot is not None else None,
            },
        )

    # Determine snapshot from max TIMESTAMP if not explicitly supplied
    if snapshot is None:
        valid_timestamps = []
        for r in rows:
            if isinstance(r, dict):
                dt = _parse_datetime_utc(r.get("TIMESTAMP"))
                if dt is not None:
                    valid_timestamps.append(dt)
        if valid_timestamps:
            snapshot = max(valid_timestamps)

    # If snapshot still cannot be determined (e.g. no valid timestamps in any row), return empty result
    if snapshot is None:
        return ParseResult(
            accepted=[],
            rejected=[],
            stats={
                "raw_rows": len(rows),
                "accepted": 0,
                "rejected": 0,
                "invalid_imo": 0,
                "invalid_mmsi": 0,
                "no_position": 0,
                "stale_position": 0,
                "duplicate": 0,
                "rejection_reasons": {
                    "invalid_imo": 0,
                    "invalid_mmsi": 0,
                    "no_position": 0,
                    "stale_position": 0,
                    "duplicate": 0,
                },
                "port_areas": {
                    "inbound": 0,
                    "in_port": 0,
                    "anchorage": 0,
                    "anchorage_bound": 0,
                    "unknown": 0,
                },
                "flag_counts": {},
                "snapshot": None,
            },
        )

    accepted: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []

    # Target port properties
    port_id = str(port.get("port_id") or "").strip()
    port_unlocode = str(port.get("unlocode") or "").strip().upper()
    home_names = [str(name).strip().upper() for name in port.get("home_names", [])]

    # Pre-parse other_ports
    parsed_other_ports: List[Dict[str, Any]] = []
    for op in other_ports:
        parsed_other_ports.append(
            {
                "unlocode": str(op.get("unlocode") or "").strip().upper(),
                "home_names": [str(name).strip().upper() for name in op.get("home_names", [])],
                "original_unlocode": op.get("unlocode"),
            }
        )

    candidates: List[Dict[str, Any]] = []

    # Pass 1: Individual row validation (Rules 6 - 9)
    for idx, row in enumerate(rows):
        imo_raw = str(row.get("IMO") or "").strip() if isinstance(row, dict) else ""
        mmsi_raw = str(row.get("MMSI") or "").strip() if isinstance(row, dict) else ""

        imo_val = imo_raw if imo_raw else None
        mmsi_val = mmsi_raw if mmsi_raw else None

        # Rule 6: IMO stripped must be exactly 7 digits
        if not (len(imo_raw) == 7 and imo_raw.isdigit()):
            rejected.append({"reason": "invalid_imo", "imo": imo_val, "mmsi": mmsi_val})
            continue

        # Rule 7: MMSI must be 9 digits starting with 2 to 7
        if not (len(mmsi_raw) == 9 and mmsi_raw.isdigit() and mmsi_raw[0] in "234567"):
            rejected.append({"reason": "invalid_mmsi", "imo": imo_val, "mmsi": mmsi_val})
            continue

        # Rule 8: Missing or non-numeric LAT/LON
        lat = _parse_float(row.get("LAT"))
        lon = _parse_float(row.get("LON"))
        if lat is None or lon is None:
            rejected.append({"reason": "no_position", "imo": imo_val, "mmsi": mmsi_val})
            continue

        # Rule 9: Stale position (> 24 hours before snapshot)
        ts = _parse_datetime_utc(row.get("TIMESTAMP"))
        if ts is None or (snapshot - ts) > timedelta(hours=24):
            rejected.append({"reason": "stale_position", "imo": imo_val, "mmsi": mmsi_val})
            continue

        candidates.append(
            {
                "row": row,
                "imo": imo_raw,
                "mmsi": mmsi_raw,
                "lat": lat,
                "lon": lon,
                "ts": ts,
                "original_index": idx,
            }
        )

    # Pass 2: Duplicate IMO resolution (Rule 10)
    # Keep the row with the latest TIMESTAMP; others rejected with reason "duplicate"
    grouped_candidates: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for cand in candidates:
        grouped_candidates[cand["imo"]].append(cand)

    final_candidates: List[Dict[str, Any]] = []
    for imo, group in grouped_candidates.items():
        if len(group) == 1:
            final_candidates.append(group[0])
        else:
            # Sort by timestamp descending. In case of tie, preserve original order
            group.sort(key=lambda x: (x["ts"], -x["original_index"]), reverse=True)
            winner = group[0]
            final_candidates.append(winner)
            for loser in group[1:]:
                rejected.append(
                    {
                        "reason": "duplicate",
                        "imo": loser["imo"],
                        "mmsi": loser["mmsi"],
                    }
                )

    # Preserve order of appearance in raw rows
    final_candidates.sort(key=lambda x: x["original_index"])

    # Pass 3: Field parsing, port area classification, and lead hints
    for cand in final_candidates:
        row = cand["row"]
        imo = cand["imo"]
        mmsi = cand["mmsi"]
        lat = cand["lat"]
        lon = cand["lon"]
        ts = cand["ts"]

        flags: List[str] = []

        # Numerical fields with Rule 2 zero-handling
        grt = _parse_float(row.get("GRT"), allow_zero=False)
        dwt = _parse_float(row.get("DWT"), allow_zero=False)
        length = _parse_float(row.get("LENGTH"), allow_zero=False)
        beam = _parse_float(row.get("WIDTH"), allow_zero=False)

        # Rule 3:
        # SPEED is knots x 10 -> speed_knots = SPEED / 10
        raw_speed = _parse_float(row.get("SPEED"), allow_zero=True)
        speed = (raw_speed / 10.0) if raw_speed is not None else None

        # ASSUMPTION: DRAUGHT is received in decimetres (metres x 10) and divided by 10 to obtain metres.
        raw_draught = _parse_float(row.get("DRAUGHT"), allow_zero=False)
        draught = (raw_draught / 10.0) if raw_draught is not None else None

        # Rule 4: YEAR_BUILT > snapshot.year is untrusted -> set to None and flag year_built_future
        year_built = _parse_int(row.get("YEAR_BUILT"), allow_zero=False)
        if year_built is not None and year_built > snapshot.year:
            year_built = None
            flags.append("year_built_future")

        # Identity and string fields
        name = str(row.get("SHIPNAME") or "").strip()
        vessel_type = str(row.get("TYPE_NAME") or "").strip()  # Rule 11
        vessel_type_code = str(row.get("SHIPTYPE") or "").strip()
        flag_val = str(row.get("ISO2") or "").strip().upper()
        callsign = str(row.get("CALLSIGN") or "").strip()
        ship_id = str(row.get("SHIP_ID") or "").strip()

        # Observation navigation telemetry
        course = _parse_float(row.get("COURSE"), allow_zero=True)
        navigational_status = _parse_int(row.get("STATUS"), allow_zero=True)
        destination = str(row.get("NEXT_PORT_NAME") or "").strip()
        next_port_unlocode = str(row.get("NEXT_PORT_UNLOCODE") or "").strip().upper()
        current_port_str = str(row.get("CURRENT_PORT") or "").strip()
        last_port_str = str(row.get("LAST_PORT") or "").strip()
        last_port_unlocode = str(row.get("LAST_PORT_UNLOCODE") or "").strip().upper()
        last_port_time = _parse_datetime_utc(row.get("LAST_PORT_TIME"))

        # Port area classification (Rule 12)
        cp = current_port_str.upper()
        next_port_id = str(row.get("NEXT_PORT_ID") or "").strip()
        next_port_name_upper = destination.upper()

        if cp.endswith(" ANCH") and any(cp.startswith(h) for h in home_names):
            port_area = "anchorage"
        elif cp in home_names:
            port_area = "in_port"
        elif not cp and port_id and next_port_id == port_id:
            port_area = "inbound"
        elif cp and port_id and next_port_id == port_id:
            port_area = "inbound"
            flags.append("inbound_from_other_port")
        elif not cp and next_port_name_upper.endswith("ANCH") and not next_port_unlocode:
            port_area = "anchorage_bound"
        else:
            port_area = "unknown"

        # ETA calculations (Rules 13 - 16)
        raw_eta_calc = row.get("ETA_CALC")
        eta_calc_dt = _parse_datetime_utc(raw_eta_calc)
        raw_eta = row.get("ETA")
        eta_dt = _parse_datetime_utc(raw_eta)
        eta_updated = _parse_datetime_utc(row.get("ETA_UPDATED"))

        if eta_calc_dt is not None:
            chosen_eta = eta_calc_dt
            eta_source = "eta_calc"
        elif eta_dt is not None:
            chosen_eta = eta_dt
            eta_source = "ais_eta"
            flags.append("eta_from_ais_only")
        else:
            chosen_eta = None
            eta_source = ""

        if chosen_eta is not None:
            if chosen_eta < snapshot:
                # Rule 14: Chosen ETA in the past
                chosen_eta = None
                eta_source = ""
                flags.append("eta_in_past")
            elif chosen_eta > (snapshot + timedelta(days=window_days)):
                # Rule 15: Chosen ETA beyond window
                flags.append("eta_beyond_window")

        # Lead hints (Rules 17 - 19)
        hours_to_eta: Optional[float] = None
        if chosen_eta is not None:
            hours_to_eta = round((chosen_eta - snapshot).total_seconds() / 3600.0, 1)

        last_port_upper = last_port_str.upper()
        last_port_is_same_port = False
        if port_unlocode and last_port_unlocode == port_unlocode:
            last_port_is_same_port = True
        elif any(last_port_upper.startswith(h) for h in home_names):
            last_port_is_same_port = True

        cleaned_last_port = last_port_upper
        if cleaned_last_port.endswith(" ANCH"):
            cleaned_last_port = cleaned_last_port[:-5].strip()

        came_from_target_port: Optional[str] = None
        for op in parsed_other_ports:
            op_unlocode = op["unlocode"]
            op_home_names = op["home_names"]
            if op_unlocode and last_port_unlocode == op_unlocode:
                came_from_target_port = op["original_unlocode"]
                break
            elif any(cleaned_last_port.startswith(h) for h in op_home_names):
                came_from_target_port = op["original_unlocode"]
                break

        vessel_dict = {
            "imo": imo,
            "mmsi": mmsi,
            "name": name,
            "vessel_type": vessel_type,
            "vessel_type_code": vessel_type_code,
            "flag": flag_val,
            "callsign": callsign,
            "ship_id": ship_id,
            "grt": grt,
            "dwt": dwt,
            "year_built": year_built,
            "length": length,
            "beam": beam,
            "draught": draught,
        }

        # Exact model field names from apps.observations.models.VesselObservation:
        # speed (not speed_knots), timestamp (not observed_at)
        observation_dict = {
            "latitude": lat,
            "longitude": lon,
            "speed": speed,
            "course": course,
            "navigational_status": navigational_status,
            "destination": destination,
            "next_port_unlocode": next_port_unlocode,
            "eta_calc": eta_calc_dt,
            "eta_updated": eta_updated,
            "last_port": last_port_str,
            "last_port_unlocode": last_port_unlocode,
            "last_port_time": last_port_time,
            "current_port": current_port_str,
            "port_area": port_area,
            "timestamp": ts,
        }

        lead_dict = {
            "is_inbound": (port_area == "inbound"),
            "eta": chosen_eta,
            "eta_source": eta_source,
            "hours_to_eta": hours_to_eta,
            "last_port_is_same_port": last_port_is_same_port,
            "came_from_target_port": came_from_target_port,
        }

        accepted.append(
            {
                "vessel": vessel_dict,
                "observation": observation_dict,
                "lead": lead_dict,
                "flags": flags,
            }
        )

    # Compute summary statistics
    rejection_counts = Counter(r["reason"] for r in rejected)
    port_area_counts = Counter(item["observation"]["port_area"] for item in accepted)
    flag_counts = Counter(flag for item in accepted for flag in item["flags"])

    stats = {
        "raw_rows": len(rows),
        "accepted": len(accepted),
        "rejected": len(rejected),
        "invalid_imo": rejection_counts.get("invalid_imo", 0),
        "invalid_mmsi": rejection_counts.get("invalid_mmsi", 0),
        "no_position": rejection_counts.get("no_position", 0),
        "stale_position": rejection_counts.get("stale_position", 0),
        "duplicate": rejection_counts.get("duplicate", 0),
        "rejection_reasons": {
            "invalid_imo": rejection_counts.get("invalid_imo", 0),
            "invalid_mmsi": rejection_counts.get("invalid_mmsi", 0),
            "no_position": rejection_counts.get("no_position", 0),
            "stale_position": rejection_counts.get("stale_position", 0),
            "duplicate": rejection_counts.get("duplicate", 0),
        },
        "port_areas": {
            "inbound": port_area_counts.get("inbound", 0),
            "in_port": port_area_counts.get("in_port", 0),
            "anchorage": port_area_counts.get("anchorage", 0),
            "anchorage_bound": port_area_counts.get("anchorage_bound", 0),
            "unknown": port_area_counts.get("unknown", 0),
        },
        "flag_counts": dict(flag_counts),
        "snapshot": snapshot.isoformat(),
    }

    return ParseResult(accepted=accepted, rejected=rejected, stats=stats)
