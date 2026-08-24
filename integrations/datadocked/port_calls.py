"""Thin wrapper for the port-calls-by-port endpoint — same pattern as
discovery.py / location.py / management.py. Handles pagination and enforces
the EXPECTED_ARRIVALS_MAX_PAGES_PER_PORT cost cap from settings."""
import logging

from django.conf import settings

from .client import DataDockedClient
from .exceptions import DataDockedError
from .parsers import parse_expected_arrivals_response

logger = logging.getLogger("vessel_intel")

SEARCH_TYPE_EXPECTED = "expected"


def fetch_expected_arrivals(port, client: DataDockedClient = None) -> list:
    """Fetch expected-arrival vessel records for *port* from DataDocked.

    Paginates up to ``settings.EXPECTED_ARRIVALS_MAX_PAGES_PER_PORT`` pages.
    If the API reports more pages than the cap, logs a warning (naming the
    port and total page count) and stops — it never silently pulls everything.

    Returns a combined flat list of normalised vessel dicts (already parsed,
    MMSI cast to str). Raises ``DataDockedError`` on the first-page failure so
    the task layer can record the error and move on to the next port.

    Credits: 50 per page fetched. The caller (tasks/expected_arrivals.py) is
    responsible for logging one EnrichmentLog row per page.
    """
    client = client or DataDockedClient()
    max_pages = getattr(settings, "EXPECTED_ARRIVALS_MAX_PAGES_PER_PORT", 3)

    # Always fetch page 1 — raises DataDockedError on failure (let it propagate)
    payload = client.get_port_calls_by_port(
        port_call=port.un_locode,
        search_type=SEARCH_TYPE_EXPECTED,
        page=1,
    )
    meta, items = parse_expected_arrivals_response(payload)

    total_pages = meta.get("pages", 1)

    if total_pages > max_pages:
        logger.warning(
            "Expected-arrivals: port %s (%s) has %d pages of results — "
            "only fetching the first %d (EXPECTED_ARRIVALS_MAX_PAGES_PER_PORT cap).",
            port.name, port.un_locode, total_pages, max_pages,
        )

    pages_to_fetch = min(total_pages, max_pages)

    # Fetch pages 2…N (page 1 already fetched above)
    for page_num in range(2, pages_to_fetch + 1):
        try:
            payload = client.get_port_calls_by_port(
                port_call=port.un_locode,
                search_type=SEARCH_TYPE_EXPECTED,
                page=page_num,
            )
            _, page_items = parse_expected_arrivals_response(payload)
            items.extend(page_items)
        except DataDockedError as exc:
            logger.warning(
                "Expected-arrivals: page %d fetch failed for port %s (%s): %s — "
                "returning partial results from pages already fetched.",
                page_num, port.name, port.un_locode, exc,
            )
            break

    return items, pages_to_fetch
