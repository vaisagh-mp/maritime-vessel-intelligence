"""Low-level HTTP client for DataDocked. All DataDocked communication is kept
here and out of Django views/models/services, per the integration-layer
isolation principle in the Phase 1 architecture."""
import logging

import requests
from django.conf import settings

from .exceptions import DataDockedRequestError, DataDockedResponseError

logger = logging.getLogger("vessel_intel")

DEFAULT_TIMEOUT = 15


class DataDockedClient:
    def __init__(self, api_key=None, base_url=None, timeout=DEFAULT_TIMEOUT):
        self.api_key = api_key or settings.DATADOCKED_API_KEY
        self.base_url = (base_url or settings.DATADOCKED_BASE_URL).rstrip("/")
        self.timeout = timeout

    def _headers(self):
        return {"x-api-key": self.api_key}

    def _get(self, endpoint: str, params: dict) -> dict:
        url = f"{self.base_url}/{endpoint}"
        try:
            response = requests.get(
                url, headers=self._headers(), params=params, timeout=self.timeout
            )
        except requests.RequestException as exc:
            logger.warning("DataDocked request failed: %s %s — %s", endpoint, params, exc)
            raise DataDockedRequestError(str(exc), endpoint=endpoint) from exc

        if not response.ok:
            logger.warning(
                "DataDocked non-2xx: %s %s — %s %s",
                endpoint, params, response.status_code, response.text[:300],
            )
            raise DataDockedResponseError(
                f"DataDocked returned {response.status_code}",
                endpoint=endpoint,
                status_code=response.status_code,
            )

        try:
            return response.json()
        except ValueError as exc:
            raise DataDockedResponseError(
                "DataDocked returned a non-JSON body", endpoint=endpoint,
                status_code=response.status_code,
            ) from exc

    def get_vessels_by_area(self, latitude: float, longitude: float, circle_radius: float) -> dict:
        return self._get(
            "get-vessels-by-area",
            {"latitude": latitude, "longitude": longitude, "circle_radius": circle_radius},
        )

    def get_vessel_location(self, imo_or_mmsi: str) -> dict:
        return self._get("get-vessel-location", {"imo_or_mmsi": imo_or_mmsi})

    def get_vessel_management_data(self, imo_or_mmsi: str) -> dict:
        return self._get("get-vessel-management-data", {"imo_or_mmsi": imo_or_mmsi})

    def get_port_calls_by_port(
        self, port_call: str, search_type: str, page: int, vessel_type: str = None
    ) -> dict:
        params = {"port_call": port_call, "search_type": search_type, "page": page}
        if vessel_type:
            params["vessel_type"] = vessel_type
        return self._get("port-calls-by-port", params)
