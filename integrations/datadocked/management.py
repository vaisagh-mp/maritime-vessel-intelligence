from .client import DataDockedClient
from .parsers import parse_management_response


def fetch_vessel_management(imo_or_mmsi: str, client: DataDockedClient = None) -> dict:
    client = client or DataDockedClient()
    payload = client.get_vessel_management_data(imo_or_mmsi)
    return parse_management_response(payload)
