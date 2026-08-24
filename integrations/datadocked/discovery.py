"""Thin wrapper tying the client + parser together for the discovery scan."""
from .client import DataDockedClient
from .parsers import parse_vessels_by_area


def fetch_vessels_by_area(port, client: DataDockedClient = None) -> list:
    client = client or DataDockedClient()
    payload = client.get_vessels_by_area(
        latitude=port.anchorage_latitude,
        longitude=port.anchorage_longitude,
        circle_radius=port.geofence_radius_km,
    )
    return parse_vessels_by_area(payload)
