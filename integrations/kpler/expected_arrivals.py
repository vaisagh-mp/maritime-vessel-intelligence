"""MarineTraffic Expected Arrivals HTTP client."""
import logging
from typing import Optional

from django.conf import settings
import requests

from .exceptions import (
    AuthenticationError,
    CallLimitError,
    ParameterError,
    ProviderRequestError,
    ServiceNotInContractError,
)
from .raw_store import save_raw_response

logger = logging.getLogger("vessel_intel")


def fetch_expected_arrivals(
    port_id: int,
    *,
    mode: str,
    timespan_days: Optional[int] = None,
    days_last_signal: Optional[int] = None,
    gt_min: Optional[int] = None,
    gt_max: Optional[int] = None,
    msgtype: str = "extended",
) -> list[dict]:
    """Fetch expected-arrivals vessel records for a given port from MarineTraffic.

    Endpoint: GET {MARINETRAFFIC_BASE_URL}/expectedarrivals/{api_key}
    Returns a list of dicts.
    """
    api_key = getattr(settings, "MARINETRAFFIC_API_KEY", "")
    if not api_key:
        raise ValueError("MARINETRAFFIC_API_KEY is not configured.")

    base_url = (getattr(settings, "MARINETRAFFIC_BASE_URL", "") or "https://services.marinetraffic.com/api").rstrip("/")
    sanitized_url = f"{base_url}/expectedarrivals/{{api_key}}"
    actual_url = f"{base_url}/expectedarrivals/{api_key}"

    # Window validation
    if timespan_days is not None and days_last_signal is not None:
        raise ValueError("Cannot provide both timespan_days and days_last_signal.")

    params = {
        "v": 4,
        "portid": port_id,
        "msgtype": msgtype,
        "protocol": "jsono",
    }

    if mode == "arrivals":
        if days_last_signal is not None:
            raise ValueError("Cannot provide days_last_signal when mode='arrivals'.")
        ts = timespan_days if timespan_days is not None else getattr(settings, "EXPECTED_ARRIVALS_TIMESPAN_DAYS", 14)
        params["timespan"] = ts
    elif mode == "inport":
        if timespan_days is not None:
            raise ValueError("Cannot provide timespan_days when mode='inport'.")
        ds = days_last_signal if days_last_signal is not None else getattr(settings, "EXPECTED_ARRIVALS_DAYS_LAST_SIGNAL", 1)
        params["days_last_signal"] = ds
    else:
        raise ValueError(f"Invalid mode {mode!r}. Must be 'arrivals' or 'inport'.")

    # Gross tonnage size-pair validation
    if (gt_min is not None and gt_max is None) or (gt_min is None and gt_max is not None):
        raise ValueError("gt_min and gt_max must be provided together or neither.")

    if gt_min is None and gt_max is None:
        default_min = getattr(settings, "EXPECTED_ARRIVALS_GT_MIN", None)
        default_max = getattr(settings, "EXPECTED_ARRIVALS_GT_MAX", None)
        if default_min is not None and default_max is not None:
            params["gt_min"] = default_min
            params["gt_max"] = default_max
    else:
        params["gt_min"] = gt_min
        params["gt_max"] = gt_max

    timeout = getattr(settings, "KPLER_HTTP_TIMEOUT_SECONDS", 30)

    try:
        response = requests.get(actual_url, params=params, timeout=timeout)
    except requests.exceptions.RequestException as exc:
        safe_msg = str(exc).replace(api_key, "{api_key}")
        logger.info(
            "MarineTraffic expectedarrivals port_id=%s mode=%s error=ProviderRequestError url=%s",
            port_id, mode, sanitized_url,
        )
        raise ProviderRequestError(f"Request failed: {safe_msg}", endpoint=sanitized_url) from exc

    if response.status_code == 429:
        logger.info(
            "MarineTraffic expectedarrivals port_id=%s mode=%s error=CallLimitError url=%s",
            port_id, mode, sanitized_url,
        )
        raise CallLimitError("Above service call limit (HTTP 429)", endpoint=sanitized_url, status_code=429)

    if response.status_code == 401:
        logger.info(
            "MarineTraffic expectedarrivals port_id=%s mode=%s error=AuthenticationError url=%s",
            port_id, mode, sanitized_url,
        )
        raise AuthenticationError("Authentication failed (HTTP 401)", endpoint=sanitized_url, status_code=401)

    try:
        data = response.json()
    except Exception as exc:
        logger.info(
            "MarineTraffic expectedarrivals port_id=%s mode=%s error=ProviderRequestError url=%s",
            port_id, mode, sanitized_url,
        )
        raise ProviderRequestError(
            f"Unparseable JSON response: {response.text[:200]}",
            endpoint=sanitized_url,
            status_code=response.status_code,
        ) from exc

    if isinstance(data, dict) and "errors" in data:
        errors = data["errors"]
        first_error = errors[0] if isinstance(errors, list) and errors else {}
        code = str(first_error.get("code", ""))
        detail = first_error.get("detail", str(first_error))
        msg = f"MarineTraffic error {code}: {detail}"

        if code == "5":
            err_cls = CallLimitError
        elif code in ("2a12", "1o"):
            err_cls = ParameterError
        elif code == "12":
            err_cls = ServiceNotInContractError
        else:
            err_cls = ProviderRequestError

        logger.info(
            "MarineTraffic expectedarrivals port_id=%s mode=%s error=%s url=%s",
            port_id, mode, err_cls.__name__, sanitized_url,
        )
        raise err_cls(msg, endpoint=sanitized_url, status_code=response.status_code, provider_code=code)

    if response.status_code >= 400:
        logger.info(
            "MarineTraffic expectedarrivals port_id=%s mode=%s error=ProviderRequestError url=%s",
            port_id, mode, sanitized_url,
        )
        raise ProviderRequestError(
            f"Provider returned HTTP {response.status_code}",
            endpoint=sanitized_url,
            status_code=response.status_code,
        )

    if not isinstance(data, list):
        logger.info(
            "MarineTraffic expectedarrivals port_id=%s mode=%s error=ProviderRequestError url=%s",
            port_id, mode, sanitized_url,
        )
        raise ProviderRequestError(
            f"Expected list of vessel records, got {type(data).__name__}",
            endpoint=sanitized_url,
            status_code=response.status_code,
        )

    try:
        save_raw_response("marinetraffic", f"port{port_id}_{mode}", data)
    except Exception as exc:
        logger.warning("Failed to save raw response for port %s (%s): %s", port_id, mode, exc)

    logger.info(
        "MarineTraffic expectedarrivals port_id=%s mode=%s rows=%d url=%s",
        port_id, mode, len(data), sanitized_url,
    )
    return data
