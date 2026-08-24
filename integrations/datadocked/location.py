from .client import DataDockedClient
from .parsers import parse_location_response


def fetch_vessel_location(imo_or_mmsi: str, client: DataDockedClient = None) -> dict:
    client = client or DataDockedClient()
    payload = client.get_vessel_location(imo_or_mmsi)
    return parse_location_response(payload)
