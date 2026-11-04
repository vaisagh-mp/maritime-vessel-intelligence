"""Kpler GraphQL client for vessel particulars and ownership."""
import json
import logging
import re
from typing import Optional

from django.conf import settings
import requests

from .exceptions import (
    AuthenticationError,
    NotEntitledError,
    ParameterError,
    ProviderRequestError,
)
from .raw_store import save_raw_response

logger = logging.getLogger("vessel_intel")

MAX_PAGES_PER_CHUNK = 5

PARTICULARS_QUERY = """query GetParticulars {
  vessels(first: __FIRST__, where: { filters: [{ field: "identifier.imo", op: IN, values: __VALUES__ }], operator: AND }, after: __AFTER__) {
    pageInfo {
      hasNextPage
      endCursor
    }
    nodes {
      identifier {
        imo
        mmsi
        callSign
        shipId
      }
      particulars {
        general {
          name
          commercialFleet
          vesselType
          vesselSubtype
          serviceStatus
          flag
          vesselSizeSegment
          keelLaidDate
        }
        hull {
          yearOfBuild
        }
        dimension {
          lengthOverall
          breadthExtreme
          draught
        }
        tonnage {
          grossTonnage
          deadweightTonnage
        }
        surveyMaintenance {
          lastDryDock
          lastRenewalSurvey
        }
      }
    }
  }
}"""

OWNERSHIP_QUERY = """query GetOwnership {
  vessels(first: __FIRST__, where: { filters: [{ field: "identifier.imo", op: IN, values: __VALUES__ }], operator: AND }, after: __AFTER__) {
    pageInfo {
      hasNextPage
      endCursor
    }
    nodes {
      identifier {
        imo
      }
      management {
        beneficialOwner {
          current {
            name
            country
            address
            website
            email
            startDate
            endDate
          }
        }
        registeredOwner {
          current {
            name
            country
            address
            website
            email
            startDate
            endDate
          }
        }
        commercialManager {
          current {
            name
            country
            address
            website
            email
            startDate
            endDate
          }
        }
        operator {
          current {
            name
            country
            address
            website
            email
            startDate
            endDate
          }
        }
        technicalManager {
          current {
            name
            country
            address
            website
            email
            startDate
            endDate
          }
        }
        ismManager {
          current {
            name
            country
            address
            website
            email
            startDate
            endDate
          }
        }
      }
      ownership {
        beneficialOwner {
          current {
            name
            country
            address
            website
            email
            startDate
            endDate
          }
        }
        registeredOwner {
          current {
            name
            country
            address
            website
            email
            startDate
            endDate
          }
        }
        ultimateBeneficialOwner {
          entityType
          name
          countryOfResidence
          startDate
          confidenceLevel
          shareholderPercentage
        }
      }
      commercial {
        disponentOwner {
          current {
            name
            country
            address
            website
            email
            startDate
            endDate
          }
        }
        commercialOperator {
          current {
            name
            country
            address
            website
            email
            startDate
            endDate
          }
        }
      }
    }
  }
}"""


def _validate_and_dedup_imos(imos: list[str]) -> list[str]:
    """Validates each IMO is exactly 7 digits after stripping; deduplicates while preserving order."""
    seen = set()
    unique_imos = []
    for imo in imos:
        if imo is None:
            raise ValueError(f"Invalid IMO: {imo!r}. Must be exactly 7 digits.")
        cleaned = str(imo).strip()
        if len(cleaned) != 7 or not cleaned.isdigit():
            raise ValueError(f"Invalid IMO: {imo!r}. Must be exactly 7 digits.")
        if cleaned not in seen:
            seen.add(cleaned)
            unique_imos.append(cleaned)
    return unique_imos


def _build_query(template: str, first: int, imos: list[str], after: Optional[str]) -> str:
    values_str = json.dumps(imos)
    after_str = json.dumps(after) if after else "null"
    return (
        template.replace("__FIRST__", str(first))
        .replace("__VALUES__", values_str)
        .replace("__AFTER__", after_str)
    )


def _handle_graphql_errors(data: dict, status_code: int, endpoint: str):
    if not isinstance(data, dict):
        return
    errors = data.get("errors")
    if not errors or not isinstance(errors, list):
        return

    first_err = errors[0] if errors else {}
    msg = first_err.get("message", "GraphQL query error")
    extensions = first_err.get("extensions") or {}
    code = extensions.get("code")

    if code == "FORBIDDEN" or status_code == 403:
        field = None
        match = re.search(r"access field \[([^\]]+)\]", msg)
        if match:
            field = match.group(1)
        elif "path" in first_err and isinstance(first_err["path"], list) and first_err["path"]:
            field = str(first_err["path"][-1])
        logger.info("Kpler GraphQL error=NotEntitledError field=%s endpoint=%s", field, endpoint)
        raise NotEntitledError(msg, field=field, endpoint=endpoint, status_code=status_code or 403)

    if code == "GRAPHQL_VALIDATION_FAILED" or status_code == 400:
        logger.info("Kpler GraphQL error=ParameterError endpoint=%s", endpoint)
        raise ParameterError(msg, endpoint=endpoint, status_code=status_code or 400)

    logger.info("Kpler GraphQL error=ProviderRequestError endpoint=%s", endpoint)
    raise ProviderRequestError(msg, endpoint=endpoint, status_code=status_code)


def _execute_graphql_query(template: str, imos: list[str], label: str) -> list[dict]:
    clean_imos = _validate_and_dedup_imos(imos)
    if not clean_imos:
        return []

    api_key = getattr(settings, "KPLER_API_KEY", "")
    if not api_key:
        raise ValueError("KPLER_API_KEY is not configured.")

    endpoint = getattr(
        settings,
        "KPLER_GRAPHQL_URL",
        "https://api.kpler.com/v2/maritime/vessels/graphql",
    )
    timeout = getattr(settings, "KPLER_HTTP_TIMEOUT_SECONDS", 30)
    page_size = getattr(settings, "KPLER_GRAPHQL_PAGE_SIZE", 100)
    if not (1 <= page_size <= 1000):
        page_size = 100

    headers = {
        "Authorization": f"Basic {api_key}",
        "Content-Type": "application/json",
    }

    chunks = [clean_imos[i : i + page_size] for i in range(0, len(clean_imos), page_size)]
    all_nodes = []

    for chunk in chunks:
        cursor = None
        for _ in range(MAX_PAGES_PER_CHUNK):
            query = _build_query(template, len(chunk), chunk, cursor)
            try:
                response = requests.post(
                    endpoint,
                    json={"query": query},
                    headers=headers,
                    timeout=timeout,
                )
            except requests.exceptions.RequestException as exc:
                safe_msg = str(exc).replace(api_key, "{api_key}")
                logger.info("Kpler GraphQL query=%s error=ProviderRequestError endpoint=%s", label, endpoint)
                raise ProviderRequestError(f"Request failed: {safe_msg}", endpoint=endpoint) from exc

            if response.status_code == 401:
                logger.info("Kpler GraphQL query=%s error=AuthenticationError endpoint=%s", label, endpoint)
                raise AuthenticationError("Authentication failed (HTTP 401)", endpoint=endpoint, status_code=401)

            try:
                data = response.json()
            except Exception as exc:
                if response.status_code == 403:
                    raise NotEntitledError("Forbidden (HTTP 403)", endpoint=endpoint, status_code=403) from exc
                if response.status_code == 400:
                    raise ParameterError(
                        f"Bad request (HTTP 400): {response.text[:200]}", endpoint=endpoint, status_code=400
                    ) from exc
                raise ProviderRequestError(
                    f"Unparseable JSON response: {response.text[:200]}",
                    endpoint=endpoint,
                    status_code=response.status_code,
                ) from exc

            _handle_graphql_errors(data, response.status_code, endpoint)

            if response.status_code >= 400:
                raise ProviderRequestError(
                    f"GraphQL endpoint returned HTTP {response.status_code}",
                    endpoint=endpoint,
                    status_code=response.status_code,
                )

            data_root = data.get("data") or {}
            vessels_data = data_root.get("vessels") or {}
            nodes = vessels_data.get("nodes") or []
            if isinstance(nodes, list):
                all_nodes.extend(nodes)

            page_info = vessels_data.get("pageInfo") or {}
            has_next_page = page_info.get("hasNextPage", False)
            cursor = page_info.get("endCursor")

            if not has_next_page or not cursor:
                break

    try:
        save_raw_response("kpler_graphql", label, all_nodes)
    except Exception as exc:
        logger.warning("Failed to save raw GraphQL response for %s: %s", label, exc)

    logger.info("Kpler GraphQL query=%s imos=%d nodes=%d", label, len(clean_imos), len(all_nodes))
    return all_nodes


def fetch_particulars(imos: list[str]) -> list[dict]:
    """Fetch vessel particulars for a list of IMOs via Kpler GraphQL."""
    return _execute_graphql_query(PARTICULARS_QUERY, imos, "particulars")


def fetch_ownership(imos: list[str]) -> list[dict]:
    """Fetch vessel ownership & management for a list of IMOs via Kpler GraphQL."""
    return _execute_graphql_query(OWNERSHIP_QUERY, imos, "ownership")
