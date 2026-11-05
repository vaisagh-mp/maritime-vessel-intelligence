"""Pure parser for Kpler Vessels GraphQL node responses."""
from typing import Any, Dict, List, Optional

from apps.common.constants import (
    RELATIONSHIP_ROLE_BENEFICIAL_OWNER,
    RELATIONSHIP_ROLE_COMMERCIAL_MANAGER,
    RELATIONSHIP_ROLE_ISM_MANAGER,
    RELATIONSHIP_ROLE_OPERATOR,
    RELATIONSHIP_ROLE_OWNER,
    RELATIONSHIP_ROLE_TECHNICAL_MANAGER,
)
from apps.common.utils import normalize_imo

ROLE_FIELD_MAPPING = {
    "registeredOwner": RELATIONSHIP_ROLE_OWNER,
    "beneficialOwner": RELATIONSHIP_ROLE_BENEFICIAL_OWNER,
    "commercialManager": RELATIONSHIP_ROLE_COMMERCIAL_MANAGER,
    "operator": RELATIONSHIP_ROLE_OPERATOR,
    "technicalManager": RELATIONSHIP_ROLE_TECHNICAL_MANAGER,
    "ismManager": RELATIONSHIP_ROLE_ISM_MANAGER,
}


def _clean_str(val: Any) -> Optional[str]:
    """Strip whitespace and return None if empty."""
    if val is None:
        return None
    s = str(val).strip()
    return s if s else None


def _clean_email(val: Any) -> Optional[str]:
    """Strip whitespace and return lowercased email, or None."""
    s = _clean_str(val)
    return s.lower() if s else None


def _coerce_float(val: Any) -> Optional[float]:
    """Coerce number safely; 0, negative, or invalid returns None."""
    if val is None:
        return None
    try:
        f = float(val)
        return f if f > 0 else None
    except (ValueError, TypeError):
        return None


def _coerce_int(val: Any) -> Optional[int]:
    """Coerce integer safely; 0, negative, or invalid returns None."""
    if val is None:
        return None
    try:
        i = int(float(val))
        return i if i > 0 else None
    except (ValueError, TypeError):
        return None


def parse_vessel_node(node: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Parse a single Kpler vessel node dictionary into normalized particulars and parties.

    Pure function: no network, no database calls.
    Returns:
        {
            "imo": str or None,
            "particulars": {
                "name": str or None,
                "callsign": str or None,
                "mmsi": str or None,
                "ship_id": str or None,
                "flag": str or None,
                "vessel_type": str or None,
                "vessel_size_segment": str or None,
                "year_built": int or None,
                "grt": float or None,
                "dwt": float or None,
                "length": float or None,
                "beam": float or None,
                "draught": float or None,
                "last_dry_dock": str or None,
                "last_renewal_survey": str or None,
            },
            "parties": [
                {
                    "role": str,
                    "name": str,
                    "country": str or None,
                    "address": str or None,
                    "website": str or None,
                    "email": str or None,
                    "start_date": str or None,
                    "end_date": str or None,
                },
                ...
            ]
        }
    """
    if not node or not isinstance(node, dict):
        return {
            "imo": None,
            "particulars": {
                "name": None,
                "callsign": None,
                "mmsi": None,
                "ship_id": None,
                "flag": None,
                "vessel_type": None,
                "vessel_size_segment": None,
                "year_built": None,
                "grt": None,
                "dwt": None,
                "length": None,
                "beam": None,
                "draught": None,
                "last_dry_dock": None,
                "last_renewal_survey": None,
            },
            "parties": [],
        }

    identifier = node.get("identifier") or {}
    imo = normalize_imo(identifier.get("imo"))
    mmsi = _clean_str(identifier.get("mmsi"))
    callsign = _clean_str(identifier.get("callSign"))
    ship_id = _clean_str(identifier.get("shipId"))

    particulars_data = node.get("particulars") or {}
    general = particulars_data.get("general") or {}
    hull = particulars_data.get("hull") or {}
    dimension = particulars_data.get("dimension") or {}
    tonnage = particulars_data.get("tonnage") or {}
    survey = particulars_data.get("surveyMaintenance") or {}

    particulars = {
        "name": _clean_str(general.get("name")),
        "callsign": callsign,
        "mmsi": mmsi,
        "ship_id": ship_id,
        "flag": _clean_str(general.get("flag")),
        "vessel_type": _clean_str(general.get("vesselType")),
        "vessel_size_segment": _clean_str(general.get("vesselSizeSegment")),
        "year_built": _coerce_int(hull.get("yearOfBuild")),
        "grt": _coerce_float(tonnage.get("grossTonnage")),
        "dwt": _coerce_float(tonnage.get("deadweightTonnage")),
        "length": _coerce_float(dimension.get("lengthOverall")),
        "beam": _coerce_float(dimension.get("breadthExtreme")),
        "draught": _coerce_float(dimension.get("draught")),
        "last_dry_dock": _clean_str(survey.get("lastDryDock")),
        "last_renewal_survey": _clean_str(survey.get("lastRenewalSurvey")),
    }

    management = node.get("management") or {}
    parties: List[Dict[str, Any]] = []

    for kpler_role_key, domain_role in ROLE_FIELD_MAPPING.items():
        role_entry = management.get(kpler_role_key)
        if not role_entry or not isinstance(role_entry, dict):
            continue

        current = role_entry.get("current")
        if not current or not isinstance(current, dict):
            continue

        name = _clean_str(current.get("name"))
        if not name:
            continue

        parties.append(
            {
                "role": domain_role,
                "name": name,
                "country": _clean_str(current.get("country")),
                "address": _clean_str(current.get("address")),
                "website": _clean_str(current.get("website")),  # As given, no lowercase
                "email": _clean_email(current.get("email")),     # Lowercase
                "start_date": _clean_str(current.get("startDate")),
                "end_date": _clean_str(current.get("endDate")),
            }
        )

    return {
        "imo": imo,
        "particulars": particulars,
        "parties": parties,
    }

