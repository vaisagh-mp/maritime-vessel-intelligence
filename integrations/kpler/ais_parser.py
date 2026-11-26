"""
integrations/kpler/ais_parser.py

Pure parser for Kpler AIS Latest GeoJSON. Standard library only: no Django, ORM,
requests, apps/ or services/ imports.

Turns each feature into the same provider-agnostic dicts the Expected Arrivals
parser produces (vessel, observation, lead) plus a ``port_area``:

    navStatus 5 (moored)                         -> "in_port"
    navStatus 1 (at anchor) or sog <= threshold  -> "anchorage"
    anything else (moving inside the area)       -> "unknown"
"""
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

NAV_AT_ANCHOR = 1
NAV_MOORED = 5


@dataclass
class AisParseResult:
    accepted: List[Dict[str, Any]]
    rejected: List[Dict[str, Any]]
    stats: Dict[str, Any]


def _float(val: Any) -> Optional[float]:
    if val is None or isinstance(val, bool):
        return None
    try:
        f = float(val)
    except (TypeError, ValueError):
        return None
    return f if f == f else None  # drop NaN


def _int(val: Any) -> Optional[int]:
    f = _float(val)
    return int(f) if f is not None else None


def _dt(val: Any) -> Optional[datetime]:
    if not val:
        return None
    try:
        dt = datetime.fromisoformat(str(val).strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _text(val: Any, limit: int) -> str:
    return str(val).strip()[:limit] if val is not None else ""


def classify_port_area(nav_status: Optional[int], sog: Optional[float], anchor_max_sog: float) -> str:
    if nav_status == NAV_MOORED:
        return "in_port"
    if nav_status == NAV_AT_ANCHOR:
        return "anchorage"
    if sog is not None and sog <= anchor_max_sog:
        return "anchorage"
    return "unknown"


def parse_ais_latest(
    payload: Any,
    *,
    snapshot: Optional[datetime] = None,
    max_age_hours: int = 24,
    anchor_max_sog: float = 1.0,
    gt_min: Optional[float] = None,
    gt_max: Optional[float] = None,
) -> AisParseResult:
    """Parse an AIS Latest FeatureCollection. Input is never mutated."""
    snapshot = snapshot or datetime.now(timezone.utc)
    features = payload.get("features") if isinstance(payload, dict) else None
    features = features if isinstance(features, list) else []

    rejected: List[Dict[str, Any]] = []
    best: Dict[str, Dict[str, Any]] = {}

    def reject(reason: str, props: Dict[str, Any]) -> None:
        rejected.append({"reason": reason, "mmsi": props.get("mmsi"), "name": props.get("vesselName")})

    for feature in features:
        if not isinstance(feature, dict):
            reject("bad_feature", {})
            continue
        props = feature.get("properties") or {}
        geometry = feature.get("geometry") or {}

        mmsi_raw = props.get("mmsi")
        mmsi = str(int(mmsi_raw)) if _int(mmsi_raw) else ""
        if not mmsi:
            reject("missing_mmsi", props)
            continue

        coords = geometry.get("coordinates") if isinstance(geometry, dict) else None
        lon = _float(coords[0]) if isinstance(coords, (list, tuple)) and len(coords) >= 2 else None
        lat = _float(coords[1]) if isinstance(coords, (list, tuple)) and len(coords) >= 2 else None
        if lon is None or lat is None:
            lon, lat = _float(props.get("longitude")), _float(props.get("latitude"))
        if lon is None or lat is None or not (-90 <= lat <= 90) or not (-180 <= lon <= 180) or (lat == 0 and lon == 0):
            reject("bad_position", props)
            continue

        pos_dt = _dt(props.get("posDt"))
        if pos_dt is None:
            reject("no_position_time", props)
            continue
        if pos_dt < snapshot - timedelta(hours=max_age_hours):
            reject("stale_position", props)
            continue

        grt = _float(props.get("grt"))
        if grt is not None and grt > 0:
            if (gt_min is not None and grt < gt_min) or (gt_max is not None and grt > gt_max):
                reject("outside_gt_range", props)
                continue

        sog = _float(props.get("sog"))
        nav = _int(props.get("navStatus"))
        port_area = classify_port_area(nav, sog, anchor_max_sog)

        imo_int = _int(props.get("imo"))
        imo = str(imo_int) if imo_int and len(str(imo_int)) == 7 else ""

        eta = _dt(props.get("eta"))
        if eta is not None and eta <= snapshot:
            eta = None
        hours_to_eta = round((eta - snapshot).total_seconds() / 3600.0, 1) if eta else None

        uid = _int(props.get("vesselUid"))
        type_code = _int(props.get("vesselTypeAis"))
        vessel = {
            "imo": imo or None,
            "mmsi": mmsi,
            "name": _text(props.get("vesselName"), 200) or f"MMSI {mmsi}",
            "vessel_type": _text(props.get("vesselType"), 120),
            "vessel_type_code": str(type_code) if type_code is not None else "",
            "flag": _text(props.get("flag"), 60),
            "callsign": _text(props.get("callsign"), 20),
            "ship_id": str(uid) if uid is not None else "",
            "grt": grt if grt and grt > 0 else None,
            "dwt": _float(props.get("dwt")) or None,
            "year_built": None,
            "length": _float(props.get("length")) or None,
            "beam": _float(props.get("width")) or None,
            "draught": _float(props.get("draught")) or None,
        }
        observation = {
            "timestamp": pos_dt,
            "latitude": lat,
            "longitude": lon,
            "speed": sog,
            "course": _float(props.get("cog")),
            "navigational_status": nav if nav is not None and 0 <= nav <= 32767 else None,
            "destination": _text(props.get("destination"), 120),
            "port_area": port_area,
        }
        lead = {
            "eta": eta,
            "eta_source": "ais_eta" if eta else "",
            "hours_to_eta": hours_to_eta,
            "is_inbound": False,
            "came_from_target_port": None,
        }
        item = {"vessel": vessel, "observation": observation, "lead": lead, "port_area": port_area}

        previous = best.get(mmsi)
        if previous is None or pos_dt > previous["observation"]["timestamp"]:
            best[mmsi] = item

    accepted = list(best.values())
    areas = Counter(i["port_area"] for i in accepted)
    reasons = Counter(r["reason"] for r in rejected)
    stats = {
        "raw_features": len(features),
        "accepted": len(accepted),
        "rejected": len(rejected),
        "rejection_reasons": dict(reasons),
        "in_anchorage": areas.get("anchorage", 0),
        "moored": areas.get("in_port", 0),
        "moving": areas.get("unknown", 0),
    }
    return AisParseResult(accepted=accepted, rejected=rejected, stats=stats)
