"""Append-only VesselObservation writer."""
from django.utils import timezone

from apps.observations.models import VesselObservation


def record_observation(vessel, raw_vessel: dict, source: str):
    def to_float(value):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    return VesselObservation.objects.create(
        vessel=vessel,
        timestamp=timezone.now(),
        latitude=to_float(raw_vessel.get("latitude")) or 0.0,
        longitude=to_float(raw_vessel.get("longitude")) or 0.0,
        speed=to_float(raw_vessel.get("speed")),
        course=to_float(raw_vessel.get("course")),
        source=source,
    )


def record_observation_from_data(vessel, obs_data: dict, source: str) -> VesselObservation:
    """Creates one VesselObservation using the parser's observation dict plus source.

    source is required. Append-only: creates a new observation, never updates.
    """
    if not source:
        raise ValueError("source is required to record a VesselObservation.")

    data = dict(obs_data)
    data["vessel"] = vessel
    data["source"] = source
    return VesselObservation.objects.create(**data)

