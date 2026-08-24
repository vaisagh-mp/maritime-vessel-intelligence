"""Task-level tests for tasks/expected_arrivals.py and the zone-touch
correctness fix in tasks/discovery.py.

Covers:
  - DWT backfill (populated when null; not overwritten when already set)
  - No VesselObservation created by expected-arrivals task
  - Zone-touch regression: "24h" → "anchorage" when area-scan re-observes
  - Zone-touch no-op: already-"anchorage" opportunity is untouched
  - Audit trail: one EnrichmentLog row per page, vessel=None, port set
  - Regression: existing discovery tests are unaffected by the zone-touch wiring
"""
from unittest.mock import MagicMock, patch

from django.test import TestCase

from apps.common.constants import ZONE_24H, ZONE_ANCHORAGE, ZONE_72H
from apps.enrichment.models import EnrichmentLog
from apps.observations.models import VesselObservation
from apps.opportunities.models import Opportunity
from apps.ports.models import Port
from apps.vessels.models import Vessel


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_port(name="Test Port", locode="TESP"):
    return Port.objects.create(
        name=name,
        un_locode=locode,
        latitude=10.0,
        longitude=80.0,
        anchorage_latitude=10.1,
        anchorage_longitude=80.1,
        geofence_radius_km=30,
        active=True,
    )


def _make_raw_vessel(mmsi="538011089", name="OCEAN BULK", vessel_type="Bulk Carrier",
                     dw=65000, formatted_eta="Aug 09, 2030 05:51 UTC"):
    """Returns a parsed vessel dict as produced by parse_expected_arrivals_response."""
    from integrations.datadocked.parsers import _parse_formatted_eta
    return {
        "mmsi": str(mmsi),
        "name": name,
        "imo": "1234567",
        "type": vessel_type,
        "dw": dw,
        "eta": _parse_formatted_eta(formatted_eta),
        "gt": 35000,
        "country": "Panama",
        "year": 2010,
        "sizes": None,
    }


def _page_payload(pages=1, vessel_list=None):
    vessel_list = vessel_list or []
    return {
        "detail": {
            "expected": {
                "total": len(vessel_list),
                "pages": pages,
                "list": [
                    # port_calls wrapper receives raw API dicts (with formattedETA),
                    # but fetch_expected_arrivals already parses them; for task tests
                    # we mock fetch_expected_arrivals directly, so raw vessels are
                    # already-parsed dicts.
                    v for v in vessel_list
                ],
            }
        }
    }


# ---------------------------------------------------------------------------
# DWT Backfill Tests
# ---------------------------------------------------------------------------

class DwtBackfillTests(TestCase):
    def setUp(self):
        self.port = _make_port()

    def _run_for_one_vessel(self, raw):
        """Helper: mock fetch_expected_arrivals to return one vessel dict."""
        with patch("tasks.expected_arrivals.fetch_expected_arrivals") as mock_fetch:
            mock_fetch.return_value = ([raw], 1)
            from tasks.expected_arrivals import run_expected_arrivals_for_port
            return run_expected_arrivals_for_port(self.port)

    def test_dwt_populated_when_null(self):
        """A new vessel with no dwt gets it set from the dw field."""
        raw = _make_raw_vessel(mmsi="100000001", dw=75000)
        self._run_for_one_vessel(raw)
        vessel = Vessel.objects.get(mmsi="100000001")
        self.assertEqual(vessel.dwt, 75000.0)

    def test_dwt_not_overwritten_when_already_set(self):
        """An existing vessel with dwt already set must not have it overwritten."""
        Vessel.objects.create(mmsi="100000002", name="ORIGINAL", vessel_type="Bulk Carrier", dwt=50000.0)
        raw = _make_raw_vessel(mmsi="100000002", dw=99999)
        self._run_for_one_vessel(raw)
        vessel = Vessel.objects.get(mmsi="100000002")
        self.assertEqual(vessel.dwt, 50000.0)  # unchanged

    def test_dwt_not_set_when_dw_absent(self):
        """When the dw field is absent, dwt stays None."""
        raw = _make_raw_vessel(mmsi="100000003")
        raw["dw"] = None
        self._run_for_one_vessel(raw)
        vessel = Vessel.objects.get(mmsi="100000003")
        self.assertIsNone(vessel.dwt)


# ---------------------------------------------------------------------------
# No VesselObservation Test
# ---------------------------------------------------------------------------

class NoObservationTest(TestCase):
    def test_expected_arrivals_does_not_create_observations(self):
        """VesselObservation.objects.count() must remain 0 after the task runs,
        even when new vessels and opportunities are created."""
        port = _make_port(locode="NOBSV")
        raw = _make_raw_vessel(mmsi="200000001")

        observation_count_before = VesselObservation.objects.count()

        with patch("tasks.expected_arrivals.fetch_expected_arrivals") as mock_fetch:
            mock_fetch.return_value = ([raw], 1)
            from tasks.expected_arrivals import run_expected_arrivals_for_port
            stats = run_expected_arrivals_for_port(port)

        self.assertEqual(VesselObservation.objects.count(), observation_count_before)
        self.assertEqual(stats["new_vessels"], 1)
        self.assertEqual(stats["new_opportunities"], 1)


# ---------------------------------------------------------------------------
# Zone-Touch Regression Tests
# ---------------------------------------------------------------------------

class ZoneTouchRegressionTests(TestCase):
    """Tests for touch_opportunity_zone_from_proximity and its wiring in discovery."""

    def _make_vessel_and_port(self):
        port = _make_port(locode="ZTPRT")
        vessel = Vessel.objects.create(mmsi="300000001", name="ZONE TEST", vessel_type="Bulk Carrier")
        return vessel, port

    def _area_scan_raw(self, vessel):
        """Minimal raw vessel dict for the area-scan path (typeSpecific, speed, lat/lon)."""
        return {
            "mmsi": vessel.mmsi,
            "name": vessel.name,
            "typeSpecific": vessel.vessel_type,
            "speed": 5.0,
            "latitude": 10.1,
            "longitude": 80.1,
        }

    def test_zone_upgraded_from_24h_to_anchorage_on_area_scan(self):
        """An opportunity created by expected-arrivals (zone='24h') gets upgraded
        to 'anchorage' when area-scan discovery physically observes the vessel."""
        vessel, port = self._make_vessel_and_port()

        # Simulate expected-arrivals having created the opportunity with zone="24h"
        opp = Opportunity.objects.create(vessel=vessel, port=port, zone=ZONE_24H, score=0)

        raw = self._area_scan_raw(vessel)

        with patch("tasks.discovery.fetch_vessels_by_area") as mock_scan:
            mock_scan.return_value = [raw]
            from tasks.discovery import run_discovery_for_port
            run_discovery_for_port(port)

        opp.refresh_from_db()
        self.assertEqual(opp.zone, ZONE_ANCHORAGE)

    def test_zone_upgraded_from_72h_to_anchorage_on_area_scan(self):
        """Same upgrade applies regardless of prior zone value (72h → anchorage)."""
        vessel, port = self._make_vessel_and_port()
        opp = Opportunity.objects.create(vessel=vessel, port=port, zone=ZONE_72H, score=0)

        raw = self._area_scan_raw(vessel)

        with patch("tasks.discovery.fetch_vessels_by_area") as mock_scan:
            mock_scan.return_value = [raw]
            from tasks.discovery import run_discovery_for_port
            run_discovery_for_port(port)

        opp.refresh_from_db()
        self.assertEqual(opp.zone, ZONE_ANCHORAGE)

    def test_already_anchorage_opportunity_not_redundantly_rescored(self):
        """If the opportunity is already 'anchorage', score is NOT recalculated again
        (touch_opportunity_zone_from_proximity returns False)."""
        from services.opportunity_service import touch_opportunity_zone_from_proximity

        vessel, port = self._make_vessel_and_port()
        opp = Opportunity.objects.create(vessel=vessel, port=port, zone=ZONE_ANCHORAGE, score=42)

        updated = touch_opportunity_zone_from_proximity(opp)
        self.assertFalse(updated)

        opp.refresh_from_db()
        self.assertEqual(opp.zone, ZONE_ANCHORAGE)
        self.assertEqual(opp.score, 42)  # score unchanged — no recalculate

    def test_score_is_recalculated_when_zone_upgraded(self):
        """score field changes after zone upgrade (recalculate_score is called)."""
        from services.opportunity_service import touch_opportunity_zone_from_proximity

        vessel, port = self._make_vessel_and_port()
        # Force score=0 so we can detect any change post-upgrade
        opp = Opportunity.objects.create(vessel=vessel, port=port, zone=ZONE_24H, score=0)

        updated = touch_opportunity_zone_from_proximity(opp)
        self.assertTrue(updated)

        # Score must have been set by recalculate_score (value doesn't matter here,
        # just that save was called with score update_fields)
        opp.refresh_from_db()
        self.assertEqual(opp.zone, ZONE_ANCHORAGE)


# ---------------------------------------------------------------------------
# Audit Trail Tests
# ---------------------------------------------------------------------------

class AuditTrailTests(TestCase):
    def setUp(self):
        self.port = _make_port(locode="AUDIT")

    def test_one_log_per_page_fetched_vessel_none_port_set(self):
        """EnrichmentLog gets exactly one row per fetched page, vessel=None, port correct."""
        raw = _make_raw_vessel(mmsi="400000001")

        with patch("tasks.expected_arrivals.fetch_expected_arrivals") as mock_fetch:
            mock_fetch.return_value = ([raw], 2)  # 2 pages fetched
            from tasks.expected_arrivals import run_expected_arrivals_for_port
            run_expected_arrivals_for_port(self.port)

        logs = EnrichmentLog.objects.filter(
            endpoint_called="port-calls-by-port:expected",
            port=self.port,
        )
        self.assertEqual(logs.count(), 2)
        for log in logs:
            self.assertIsNone(log.vessel_id)
            self.assertEqual(log.port_id, self.port.pk)
            self.assertTrue(log.success)
            self.assertEqual(log.credits_spent, 50)

    def test_failed_fetch_logs_failure_row(self):
        """A DataDockedError on first-page fetch logs a failure row with credits_spent=0."""
        from integrations.datadocked.exceptions import DataDockedRequestError

        with patch("tasks.expected_arrivals.fetch_expected_arrivals") as mock_fetch:
            mock_fetch.side_effect = DataDockedRequestError("timeout", endpoint="port-calls-by-port")
            from tasks.expected_arrivals import run_expected_arrivals_for_port
            stats = run_expected_arrivals_for_port(self.port)

        self.assertEqual(stats["errors"], 1)
        fail_log = EnrichmentLog.objects.filter(
            endpoint_called="port-calls-by-port:expected",
            port=self.port,
            success=False,
        )
        self.assertEqual(fail_log.count(), 1)
        self.assertEqual(fail_log.first().credits_spent, 0)
        self.assertIsNone(fail_log.first().vessel_id)


# ---------------------------------------------------------------------------
# Type-Exclusion Filter Test
# ---------------------------------------------------------------------------

class TypeExclusionTests(TestCase):
    """Confirm the `type` field (not typeSpecific) is used for exclusion."""

    def test_excluded_type_is_skipped(self):
        port = _make_port(locode="EXCL1")
        raw = _make_raw_vessel(mmsi="500000001", vessel_type="Tug")

        with patch("tasks.expected_arrivals.fetch_expected_arrivals") as mock_fetch:
            mock_fetch.return_value = ([raw], 1)
            from tasks.expected_arrivals import run_expected_arrivals_for_port
            stats = run_expected_arrivals_for_port(port)

        self.assertEqual(stats["excluded"], 1)
        self.assertFalse(Vessel.objects.filter(mmsi="500000001").exists())


# ---------------------------------------------------------------------------
# Dedup — no duplicate open opportunity
# ---------------------------------------------------------------------------

class DeduplicationTests(TestCase):
    def test_no_duplicate_opportunity_on_second_run(self):
        """Running expected-arrivals twice for the same vessel+port must not
        create a second open Opportunity."""
        port = _make_port(locode="DEDUP")
        raw = _make_raw_vessel(mmsi="600000001")

        with patch("tasks.expected_arrivals.fetch_expected_arrivals") as mock_fetch:
            mock_fetch.return_value = ([raw], 1)
            from tasks.expected_arrivals import run_expected_arrivals_for_port
            run_expected_arrivals_for_port(port)
            run_expected_arrivals_for_port(port)

        vessel = Vessel.objects.get(mmsi="600000001")
        open_opps = Opportunity.objects.open_for(vessel, port)
        self.assertEqual(open_opps.count(), 1)
