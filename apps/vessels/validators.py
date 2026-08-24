from apps.common.utils import is_type_excluded
from django.conf import settings


def is_vessel_type_excluded(type_specific: str) -> bool:
    return is_type_excluded(type_specific, settings.VESSEL_TYPE_EXCLUSIONS)


def is_aid_to_navigation_mmsi(mmsi: str) -> bool:
    """MMSI numbers starting with 99 are reserved for Aids to Navigation
    (buoys, lights, beacons) under the ITU MID numbering scheme — this is a
    structural identity check, independent of whatever text DataDocked
    returns in typeSpecific."""
    return bool(mmsi) and str(mmsi).startswith("99")


def is_implausible_speed(speed) -> bool:
    """Checks if speed exceeds MAX_PLAUSIBLE_VESSEL_SPEED_KNOTS.
    Missing or unparseable speed is treated as not excluded."""
    if speed is None:
        return False
    try:
        val = float(speed)
    except (TypeError, ValueError):
        return False
    max_speed = getattr(settings, "MAX_PLAUSIBLE_VESSEL_SPEED_KNOTS", 60)
    return val > max_speed


def is_vessel_name_excluded(name: str, type_specific: str) -> bool:
    """Fallback check for vessel names when type_specific is missing, empty, or 'Unknown'.
    Applied only as a fallback to avoid accidentally filtering legitimate vessels with keywords in their name."""
    if type_specific and str(type_specific).strip().lower() not in ("", "unknown"):
        return False
    if not name:
        return False
    keywords = getattr(settings, "VESSEL_NAME_EXCLUSION_KEYWORDS", [])
    name_lower = str(name).lower()
    return any(keyword.lower() in name_lower for keyword in keywords)
