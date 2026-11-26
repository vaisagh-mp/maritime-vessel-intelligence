"""Kpler AIS Latest API client (GET/POST /v2/maritime/ais-latest).

Returns the most recent known position (past 7 days) per vessel that matches an
ECQL filter. The area filter text comes from ``Port.ais_filter`` exactly as the
provider supplied it. The API key is sent in the Authorization header and never
appears in URLs, logs, exceptions or saved files.
"""
import logging
from typing import Any, Dict, Optional

import requests
from django.conf import settings

from .exceptions import (
    AuthenticationError,
    CallLimitError,
    KplerAccessError,
    ParameterError,
    ProviderRequestError,
)
from .raw_store import save_raw_response

logger = logging.getLogger("vessel_intel")

MAX_BODY_CHARS = 300


def get_ais_api_key() -> str:
    """AIS key: KPLER_AIS_API_KEY when set, otherwise KPLER_API_KEY."""
    key = (getattr(settings, "KPLER_AIS_API_KEY", "") or "").strip()
    if not key:
        key = (getattr(settings, "KPLER_API_KEY", "") or "").strip()
    return key


def _clean(text: Any, api_key: str) -> str:
    out = str(text)
    if api_key:
        out = out.replace(api_key, "{api_key}")
    return out[:MAX_BODY_CHARS]


def fetch_ais_latest(
    filter_text: str,
    *,
    limit: Optional[int] = None,
    label: str = "latest",
    save_raw: bool = True,
) -> Dict[str, Any]:
    """Call AIS Latest once (POST, so long area filters are fine) and return the GeoJSON dict."""
    api_key = get_ais_api_key()
    if not api_key:
        raise ValueError("KPLER_AIS_API_KEY / KPLER_API_KEY is not configured.")
    filter_text = (filter_text or "").strip()
    if not filter_text:
        raise ValueError("The AIS area filter is empty. Set Port.ais_filter first.")

    endpoint = getattr(settings, "KPLER_AIS_URL", "https://api.kpler.com/v2/maritime/ais-latest")
    timeout = getattr(settings, "KPLER_HTTP_TIMEOUT_SECONDS", 30)
    max_rows = limit or getattr(settings, "AIS_LATEST_LIMIT", 5000)

    headers = {
        "Authorization": f"Basic {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    body = {"filter": filter_text, "format": "json", "limit": int(max_rows)}

    try:
        response = requests.post(endpoint, json=body, headers=headers, timeout=timeout)
    except requests.exceptions.RequestException as exc:
        logger.info("Kpler AIS Latest error=ProviderRequestError endpoint=%s", endpoint)
        raise ProviderRequestError(f"Request failed: {_clean(exc, api_key)}", endpoint=endpoint) from exc

    status = response.status_code
    if status == 401:
        raise AuthenticationError("Authentication failed (HTTP 401)", endpoint=endpoint, status_code=401)
    if status == 403:
        raise KplerAccessError(
            "AIS Latest is not enabled for this key (HTTP 403)", endpoint=endpoint, status_code=403
        )
    if status == 429:
        raise CallLimitError("Rate limit exceeded (HTTP 429)", endpoint=endpoint, status_code=429)
    if status == 400:
        raise ParameterError(
            f"Invalid request or area filter (HTTP 400): {_clean(response.text, api_key)}",
            endpoint=endpoint,
            status_code=400,
        )
    if status >= 400:
        raise ProviderRequestError(f"Provider error (HTTP {status})", endpoint=endpoint, status_code=status)

    try:
        payload = response.json()
    except ValueError as exc:
        raise ProviderRequestError("Provider returned a body that is not JSON", endpoint=endpoint) from exc

    if not isinstance(payload, dict) or not isinstance(payload.get("features"), list):
        raise ProviderRequestError("Unexpected AIS Latest response shape", endpoint=endpoint)

    if save_raw:
        try:
            save_raw_response("kpler_ais", label, payload)
        except OSError:
            logger.warning("Could not save the raw AIS Latest response")
    logger.info(
        "Kpler AIS Latest label=%s features=%s matched=%s",
        label,
        len(payload["features"]),
        payload.get("numberMatched"),
    )
    return payload
