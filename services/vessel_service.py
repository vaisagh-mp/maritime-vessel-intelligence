"""Vessel identity creation/update + multi-signal exclusion enforcement."""
import logging

from apps.vessels.models import Vessel
from apps.vessels.validators import (
    is_aid_to_navigation_mmsi,
    is_implausible_speed,
    is_vessel_name_excluded,
    is_vessel_type_excluded,
)

logger = logging.getLogger("vessel_intel")


def get_or_create_vessel(raw_vessel: dict):
    """Creates/updates a Vessel from a raw discovery record (provider-agnostic shape),
    keyed by MMSI (the area-scan endpoint doesn't return IMO). Returns (vessel, created) or
    (None, False) if excluded by MMSI prefix, implausible speed, type, or name fallback.
    """
    mmsi = raw_vessel.get("mmsi")
    if not mmsi:
        logger.warning("Discovery record missing mmsi, skipping: %s", raw_vessel)
        return None, False

    if is_aid_to_navigation_mmsi(str(mmsi)):
        return None, False

    speed = raw_vessel.get("speed")
    if is_implausible_speed(speed):
        logger.warning(
            "Implausible vessel speed %s knots for vessel %s (MMSI: %s), skipping",
            speed,
            raw_vessel.get("name", "") or "",
            mmsi,
        )
        return None, False

    type_specific = raw_vessel.get("typeSpecific", "") or ""
    if is_vessel_type_excluded(type_specific):
        return None, False

    name = raw_vessel.get("name", "") or ""
    if is_vessel_name_excluded(name, type_specific):
        return None, False

    vessel, created = Vessel.objects.update_or_create(
        mmsi=mmsi,
        defaults={
            "name": name,
            "vessel_type": type_specific,
        },
    )
    return vessel, created
