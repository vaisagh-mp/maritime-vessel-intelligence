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


def upsert_vessel(vessel_data: dict) -> tuple[Vessel | None, str]:
    """Upsert a Vessel from cleaned provider-agnostic data (vessel dict from arrivals_parser).
    Returns (vessel, "created" | "updated" | "excluded").

    Identity:
    - Look up by imo first (using .filter().order_by("id").first() as IMO is not unique).
    - If not found, look up by mmsi. If that vessel has an empty imo, fill it in.
    - If neither found, create a new Vessel.

    Exclusions (returns (None, "excluded")):
    - MMSI starting with "99" (Aids to Navigation)
    - Type excluded by is_vessel_type_excluded
    - Name fallback check via is_vessel_name_excluded

    Update rules:
    - Set a field only when the new value is not None and not empty string ("").
    - NEVER overwrite an existing value with a blank.
    - Exception: name, flag, vessel_type may change to a different non-blank value.
    - Save with update_fields (plus "updated_at") only when something changed.
    """
    mmsi = vessel_data.get("mmsi")
    mmsi_str = str(mmsi).strip() if mmsi is not None else ""
    if not mmsi_str:
        return None, "excluded"

    # 1. Exclusions
    if is_aid_to_navigation_mmsi(mmsi_str):
        return None, "excluded"

    vessel_type = vessel_data.get("vessel_type", "") or ""
    if is_vessel_type_excluded(vessel_type):
        return None, "excluded"

    name = vessel_data.get("name", "") or ""
    if is_vessel_name_excluded(name, vessel_type):
        return None, "excluded"

    imo = vessel_data.get("imo")
    imo_str = str(imo).strip() if imo is not None else ""

    # 2. Identity lookup
    vessel = None
    if imo_str:
        vessel = Vessel.objects.filter(imo=imo_str).order_by("id").first()

    if vessel is None:
        vessel = Vessel.objects.filter(mmsi=mmsi_str).order_by("id").first()

    fields_to_sync = [
        "name",
        "vessel_type",
        "vessel_type_code",
        "flag",
        "callsign",
        "ship_id",
        "grt",
        "dwt",
        "year_built",
        "length",
        "beam",
        "draught",
    ]

    # 3. Create or update
    if vessel is None:
        create_kwargs = {"mmsi": mmsi_str}
        if imo_str:
            create_kwargs["imo"] = imo_str
        for field in fields_to_sync:
            val = vessel_data.get(field)
            if val is not None and val != "":
                create_kwargs[field] = val
        vessel = Vessel.objects.create(**create_kwargs)
        return vessel, "created"

    changed_fields = []
    # If existing vessel had empty IMO and we found one, fill it in
    if not vessel.imo and imo_str:
        vessel.imo = imo_str
        changed_fields.append("imo")

    for field in fields_to_sync:
        new_val = vessel_data.get(field)
        if new_val is not None and new_val != "":
            curr_val = getattr(vessel, field)
            if field in ("name", "flag", "vessel_type"):
                if curr_val != new_val:
                    setattr(vessel, field, new_val)
                    changed_fields.append(field)
            else:
                if curr_val is None or curr_val == "":
                    setattr(vessel, field, new_val)
                    changed_fields.append(field)

    if changed_fields:
        vessel.save(update_fields=list(set(changed_fields)) + ["updated_at"])

    return vessel, "updated"

