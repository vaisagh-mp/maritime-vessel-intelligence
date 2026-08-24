"""Tests for the expected-arrivals parser and the port_calls pagination wrapper."""
import logging
from unittest.mock import MagicMock, call, patch

from django.test import TestCase

from integrations.datadocked.parsers import (
    parse_expected_arrivals_response,
    _parse_formatted_eta,
)


def _make_payload(pages=1, total=1, vessel_list=None):
    """Helper: build a minimal valid port-calls-by-port expected response."""
    if vessel_list is None:
        vessel_list = []
    return {
        "detail": {
            "expected": {
                "total": total,
                "pages": pages,
                "list": vessel_list,
            }
        }
    }


def _make_vessel(mmsi=538011089, name="TEST VESSEL", vessel_type="Bulk Carrier",
                 dw=65000, formatted_eta="Aug 09, 2026 05:51 UTC"):
    return {
        "mmsi": mmsi,
        "name": name,
        "imo": "1234567",
        "type": vessel_type,
        "year": 2010,
        "country": "Panama",
        "gt": 35000,
        "dw": dw,
        "sizes": None,
        "formattedETA": formatted_eta,
    }


class ExpectedArrivalsParserTests(TestCase):
    # ------------------------------------------------------------------
    # Basic structure
    # ------------------------------------------------------------------
    def test_valid_response_parses_correctly(self):
        payload = _make_payload(pages=2, total=1, vessel_list=[_make_vessel()])
        meta, items = parse_expected_arrivals_response(payload)

        self.assertEqual(meta["pages"], 2)
        self.assertEqual(meta["total"], 1)
        self.assertEqual(len(items), 1)

        item = items[0]
        self.assertEqual(item["name"], "TEST VESSEL")
        self.assertEqual(item["dw"], 65000)
        self.assertIsNotNone(item["eta"])

    def test_empty_response_returns_zero_items(self):
        meta, items = parse_expected_arrivals_response({})
        self.assertEqual(meta["pages"], 1)
        self.assertEqual(items, [])

    def test_empty_list_key_returns_zero_items(self):
        payload = _make_payload(pages=1, total=0, vessel_list=[])
        _, items = parse_expected_arrivals_response(payload)
        self.assertEqual(items, [])

    # ------------------------------------------------------------------
    # MMSI integer → string cast
    # ------------------------------------------------------------------
    def test_mmsi_integer_cast_to_string(self):
        payload = _make_payload(vessel_list=[_make_vessel(mmsi=538011089)])
        _, items = parse_expected_arrivals_response(payload)
        self.assertIsInstance(items[0]["mmsi"], str)
        self.assertEqual(items[0]["mmsi"], "538011089")

    def test_mmsi_already_string_preserved(self):
        payload = _make_payload(vessel_list=[_make_vessel(mmsi="538011089")])
        _, items = parse_expected_arrivals_response(payload)
        self.assertEqual(items[0]["mmsi"], "538011089")

    def test_null_mmsi_becomes_none(self):
        vessel = _make_vessel()
        vessel["mmsi"] = None
        payload = _make_payload(vessel_list=[vessel])
        _, items = parse_expected_arrivals_response(payload)
        self.assertIsNone(items[0]["mmsi"])

    # ------------------------------------------------------------------
    # formattedETA parsing
    # ------------------------------------------------------------------
    def test_primary_format_parsed(self):
        eta = _parse_formatted_eta("Aug 09, 2026 05:51 UTC")
        self.assertIsNotNone(eta)
        self.assertEqual((eta.year, eta.month, eta.day, eta.hour, eta.minute),
                         (2026, 8, 9, 5, 51))

    def test_iso_format_parsed_via_dateutil_fallback(self):
        eta = _parse_formatted_eta("2026-08-09T05:51:00Z")
        self.assertIsNotNone(eta)
        self.assertEqual(eta.year, 2026)
        self.assertIsNotNone(eta.tzinfo)

    def test_unparseable_eta_returns_none_and_logs_warning(self):
        with self.assertLogs("vessel_intel", level="WARNING") as cm:
            result = _parse_formatted_eta("DEFINITELY_NOT_A_DATE_XYZ")
        self.assertIsNone(result)
        self.assertTrue(any("could not parse formattedETA" in msg for msg in cm.output))

    def test_none_eta_returns_none_without_log(self):
        result = _parse_formatted_eta(None)
        self.assertIsNone(result)

    def test_empty_string_eta_returns_none_without_log(self):
        result = _parse_formatted_eta("")
        self.assertIsNone(result)

    def test_unparseable_eta_does_not_raise(self):
        """Malformed ETA must never abort the batch — no exception propagates."""
        try:
            _parse_formatted_eta("not a date")
        except Exception as exc:
            self.fail(f"_parse_formatted_eta raised unexpectedly: {exc}")

    def test_bad_eta_in_batch_sets_eta_none_for_that_item_only(self):
        """One bad ETA record yields eta=None for that item; others are unaffected."""
        good = _make_vessel(mmsi=111111111, formatted_eta="Aug 09, 2026 05:51 UTC")
        bad = _make_vessel(mmsi=222222222, formatted_eta="GARBAGE_ETA")
        payload = _make_payload(vessel_list=[good, bad])

        with self.assertLogs("vessel_intel", level="WARNING"):
            _, items = parse_expected_arrivals_response(payload)

        self.assertIsNotNone(items[0]["eta"])
        self.assertIsNone(items[1]["eta"])


class PaginationCapTests(TestCase):
    """Ensure the port_calls wrapper respects EXPECTED_ARRIVALS_MAX_PAGES_PER_PORT."""

    def _port(self, name="Test Port", locode="TESP"):
        port = MagicMock()
        port.name = name
        port.un_locode = locode
        return port

    def _page_payload(self, pages, items=None):
        return _make_payload(pages=pages, total=pages * 5, vessel_list=items or [])

    @patch("integrations.datadocked.port_calls.DataDockedClient")
    def test_cap_limits_pages_fetched(self, MockClient):
        """When API reports 5 pages but cap is 3, only 3 client calls are made."""
        client_instance = MockClient.return_value
        # Page 1 reports 5 total pages
        client_instance.get_port_calls_by_port.return_value = self._page_payload(pages=5)

        with self.settings(EXPECTED_ARRIVALS_MAX_PAGES_PER_PORT=3):
            from integrations.datadocked.port_calls import fetch_expected_arrivals
            port = self._port()
            _, pages_fetched = fetch_expected_arrivals(port, client=client_instance)

        self.assertEqual(pages_fetched, 3)
        self.assertEqual(client_instance.get_port_calls_by_port.call_count, 3)

    @patch("integrations.datadocked.port_calls.DataDockedClient")
    def test_cap_exceeded_logs_warning(self, MockClient):
        """A warning naming the port and total page count is logged when capped."""
        client_instance = MockClient.return_value
        client_instance.get_port_calls_by_port.return_value = self._page_payload(pages=5)

        with self.settings(EXPECTED_ARRIVALS_MAX_PAGES_PER_PORT=3):
            from integrations.datadocked.port_calls import fetch_expected_arrivals
            port = self._port(name="Chittagong Port", locode="BDCGP")
            with self.assertLogs("vessel_intel", level="WARNING") as cm:
                fetch_expected_arrivals(port, client=client_instance)

        warning_text = " ".join(cm.output)
        self.assertIn("Chittagong Port", warning_text)
        self.assertIn("5", warning_text)   # total pages reported
        self.assertIn("3", warning_text)   # cap applied

    @patch("integrations.datadocked.port_calls.DataDockedClient")
    def test_no_warning_when_within_cap(self, MockClient):
        """No warning is logged when the actual page count is within the cap."""
        client_instance = MockClient.return_value
        client_instance.get_port_calls_by_port.return_value = self._page_payload(pages=2)

        with self.settings(EXPECTED_ARRIVALS_MAX_PAGES_PER_PORT=3):
            from integrations.datadocked.port_calls import fetch_expected_arrivals
            port = self._port()
            import logging
            with self.assertLogs("vessel_intel", level="DEBUG") as cm:
                # Inject a dummy DEBUG log so assertLogs doesn't fail on empty
                logging.getLogger("vessel_intel").debug("dummy")
                fetch_expected_arrivals(port, client=client_instance)

        # No cap warning should appear
        self.assertFalse(
            any("EXPECTED_ARRIVALS_MAX_PAGES_PER_PORT cap" in msg for msg in cm.output)
        )

    @patch("integrations.datadocked.port_calls.DataDockedClient")
    def test_single_page_result_fetches_exactly_once(self, MockClient):
        """Single-page API responses result in exactly one client call."""
        client_instance = MockClient.return_value
        client_instance.get_port_calls_by_port.return_value = self._page_payload(pages=1)

        with self.settings(EXPECTED_ARRIVALS_MAX_PAGES_PER_PORT=3):
            from integrations.datadocked.port_calls import fetch_expected_arrivals
            _, pages_fetched = fetch_expected_arrivals(self._port(), client=client_instance)

        self.assertEqual(pages_fetched, 1)
        client_instance.get_port_calls_by_port.assert_called_once()
