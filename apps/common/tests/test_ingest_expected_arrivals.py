"""
apps/common/tests/test_ingest_expected_arrivals.py

Unit tests for the ingest_expected_arrivals management command and underlying services.
All provider access is mocked; tests check CLI arguments, dry-run, deduplication,
exclusion rules, opportunity zone assignments, error isolation, pause intervals,
security, and architecture boundary invariants.
"""

import ast
import glob
import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from io import StringIO
from unittest.mock import MagicMock, call, patch

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from apps.common.constants import (
    SOURCE_MARINETRAFFIC_EXPECTED_ARRIVALS,
    ZONE_24H,
    ZONE_72H,
    ZONE_ANCHORAGE,
)
from apps.enrichment.models import EnrichmentLog
from apps.observations.models import VesselObservation
from apps.opportunities.models import Opportunity
from apps.ports.models import Port
from apps.vessels.models import Vessel
from integrations.kpler.exceptions import CallLimitError, ProviderRequestError


def make_synthetic_row(**overrides):
    """Helper to generate a valid synthetic row for arrivals ingestion."""
    base = {
        "IMO": "9000001",
        "MMSI": "211000001",
        "SHIPNAME": "SYNTHETIC VESSEL ONE",
        "TYPE_NAME": "Crude Oil Tanker",
        "SHIPTYPE": "80",
        "ISO2": "PA",
        "CALLSIGN": "ABCD1",
        "SHIP_ID": "10001",
        "GRT": "50000",
        "DWT": "100000",
        "YEAR_BUILT": "2018",
        "LENGTH": "250.0",
        "WIDTH": "44.0",
        "DRAUGHT": "120",  # 12.0 m
        "LAT": "1.2500",
        "LON": "103.8000",
        "SPEED": "125",    # 12.5 knots
        "COURSE": "180.0",
        "STATUS": "0",
        "NEXT_PORT_NAME": "SINGAPORE",
        "NEXT_PORT_ID": "290",
        "NEXT_PORT_UNLOCODE": "SGSIN",
        "ETA_CALC": (datetime.now(timezone.utc) + timedelta(hours=10)).strftime("%Y-%m-%dT%H:%M:%S"),
        "ETA": (datetime.now(timezone.utc) + timedelta(hours=12)).strftime("%Y-%m-%dT%H:%M:%S"),
        "ETA_UPDATED": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
        "LAST_PORT": "PORT KLANG",
        "LAST_PORT_UNLOCODE": "MYPKG",
        "LAST_PORT_TIME": (datetime.now(timezone.utc) - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%S"),
        "CURRENT_PORT": "",
        "TIMESTAMP": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
    }
    base.update(overrides)
    return base


class TestIngestExpectedArrivalsCommand(TestCase):
    """Test suite for ingest_expected_arrivals command."""

    def setUp(self):
        # Create pilot test ports
        self.port_sg = Port.objects.create(
            name="Singapore",
            un_locode="SGSIN",
            latitude=1.290270,
            longitude=103.851959,
            anchorage_latitude=1.25,
            anchorage_longitude=103.80,
            geofence_radius_km=30.0,
            marinetraffic_port_id=290,
            active=True,
        )
        self.port_fjr = Port.objects.create(
            name="Fujairah",
            un_locode="AEFJR",
            latitude=25.1288,
            longitude=56.3265,
            anchorage_latitude=25.18,
            anchorage_longitude=56.36,
            geofence_radius_km=30.0,
            marinetraffic_port_id=790,
            active=True,
        )

    # 1. No --live and no --from-file raises CommandError and client is never called
    @patch("apps.common.management.commands.ingest_expected_arrivals.fetch_expected_arrivals")
    def test_no_live_and_no_from_file_raises_command_error(self, mock_fetch):
        with self.assertRaises(CommandError) as ctx:
            call_command("ingest_expected_arrivals", mode="arrivals")
        self.assertIn("Either --live or --from-file PATH must be specified", str(ctx.exception))
        mock_fetch.assert_not_called()

    # 2. --from-file works with bare list and envelope; no client call
    @patch("apps.common.management.commands.ingest_expected_arrivals.fetch_expected_arrivals")
    def test_from_file_works_with_bare_list_and_envelope(self, mock_fetch):
        # Case A: bare list
        rows_bare = [make_synthetic_row(IMO="9000001", MMSI="211000001")]
        with tempfile.NamedTemporaryFile("w+", delete=False, suffix=".json") as f:
            json.dump(rows_bare, f)
            temp_path_bare = f.name

        try:
            call_command(
                "ingest_expected_arrivals",
                mode="arrivals",
                from_file=temp_path_bare,
                ports=["SGSIN"],
            )
            mock_fetch.assert_not_called()
            self.assertEqual(Vessel.objects.filter(imo="9000001").count(), 1)
        finally:
            if os.path.exists(temp_path_bare):
                os.remove(temp_path_bare)

        # Case B: raw envelope with "payload" key
        rows_envelope = {"payload": [make_synthetic_row(IMO="9000002", MMSI="211000002")]}
        with tempfile.NamedTemporaryFile("w+", delete=False, suffix=".json") as f:
            json.dump(rows_envelope, f)
            temp_path_envelope = f.name

        try:
            call_command(
                "ingest_expected_arrivals",
                mode="arrivals",
                from_file=temp_path_envelope,
                ports=["SGSIN"],
            )
            mock_fetch.assert_not_called()
            self.assertEqual(Vessel.objects.filter(imo="9000002").count(), 1)
        finally:
            if os.path.exists(temp_path_envelope):
                os.remove(temp_path_envelope)

    # 3. --dry-run writes no Vessel, Observation or Opportunity but prints stats
    @patch("apps.common.management.commands.ingest_expected_arrivals.fetch_expected_arrivals")
    def test_dry_run_persists_nothing_but_prints_stats(self, mock_fetch):
        mock_fetch.return_value = [make_synthetic_row(IMO="9000001", MMSI="211000001")]
        out = StringIO()

        call_command(
            "ingest_expected_arrivals",
            mode="arrivals",
            live=True,
            dry_run=True,
            ports=["SGSIN"],
            stdout=out,
        )

        self.assertEqual(Vessel.objects.count(), 0)
        self.assertEqual(VesselObservation.objects.count(), 0)
        self.assertEqual(Opportunity.objects.count(), 0)

        output = out.getvalue()
        self.assertIn("[DRY-RUN - NO CHANGES PERSISTED]", output)
        self.assertIn("Vessels created: 1", output)
        self.assertIn("Observations created: 1", output)

    # 4. A new row creates a Vessel, one Observation, and the right port_area
    @patch("apps.common.management.commands.ingest_expected_arrivals.fetch_expected_arrivals")
    def test_new_row_creates_vessel_observation_opportunity(self, mock_fetch):
        mock_fetch.return_value = [
            make_synthetic_row(
                IMO="9000001",
                MMSI="211000001",
                GRT="55000",
                DWT="110000",
                YEAR_BUILT="2019",
                ISO2="SG",
                CURRENT_PORT="",
                NEXT_PORT_ID="290",
            )
        ]

        call_command("ingest_expected_arrivals", mode="arrivals", live=True, ports=["SGSIN"])

        vessel = Vessel.objects.get(imo="9000001")
        self.assertEqual(vessel.mmsi, "211000001")
        self.assertEqual(vessel.grt, 55000.0)
        self.assertEqual(vessel.dwt, 110000.0)
        self.assertEqual(vessel.year_built, 2019)
        self.assertEqual(vessel.flag, "SG")

        obs = VesselObservation.objects.get(vessel=vessel)
        self.assertEqual(obs.source, SOURCE_MARINETRAFFIC_EXPECTED_ARRIVALS)
        self.assertEqual(obs.port_area, "inbound")

        opp = Opportunity.objects.get(vessel=vessel, port=self.port_sg)
        self.assertEqual(opp.zone, ZONE_24H)
        self.assertTrue(opp.is_inbound)

    # 5. A second run for the same rows creates NO new Vessel but adds an Observation
    @patch("apps.common.management.commands.ingest_expected_arrivals.fetch_expected_arrivals")
    def test_second_run_appends_observation_without_duplicating_vessel_or_opportunity(
        self, mock_fetch
    ):
        mock_fetch.return_value = [make_synthetic_row(IMO="9000001", MMSI="211000001")]

        call_command("ingest_expected_arrivals", mode="arrivals", live=True, ports=["SGSIN"])
        call_command("ingest_expected_arrivals", mode="arrivals", live=True, ports=["SGSIN"])

        self.assertEqual(Vessel.objects.filter(imo="9000001").count(), 1)
        self.assertEqual(VesselObservation.objects.filter(vessel__imo="9000001").count(), 2)
        self.assertEqual(Opportunity.objects.filter(vessel__imo="9000001").count(), 1)

    # 6. Identity lookup rules
    @patch("apps.common.management.commands.ingest_expected_arrivals.fetch_expected_arrivals")
    def test_identity_lookup_rules(self, mock_fetch):
        # A: Vessel found by MMSI with empty IMO gets the IMO filled
        vessel_no_imo = Vessel.objects.create(
            mmsi="211000010",
            name="Vessel Without IMO",
            imo=None,
        )
        mock_fetch.return_value = [
            make_synthetic_row(IMO="9000010", MMSI="211000010", SHIPNAME="Vessel With IMO Added")
        ]
        call_command("ingest_expected_arrivals", mode="arrivals", live=True, ports=["SGSIN"])

        vessel_no_imo.refresh_from_db()
        self.assertEqual(vessel_no_imo.imo, "9000010")

        # B: Two existing vessels with the same IMO do not crash
        Vessel.objects.create(mmsi="211000020", imo="9000020", name="Duplicate IMO 1")
        Vessel.objects.create(mmsi="211000021", imo="9000020", name="Duplicate IMO 2")

        mock_fetch.return_value = [make_synthetic_row(IMO="9000020", MMSI="211000020")]
        # Must execute cleanly without MultipleObjectsReturned
        call_command("ingest_expected_arrivals", mode="arrivals", live=True, ports=["SGSIN"])

    # 7. A blank incoming value never overwrites an existing value
    @patch("apps.common.management.commands.ingest_expected_arrivals.fetch_expected_arrivals")
    def test_blank_incoming_value_never_overwrites_existing(self, mock_fetch):
        vessel = Vessel.objects.create(
            imo="9000030",
            mmsi="211000030",
            name="Existing Tanker",
            callsign="CALL1",
            dwt=80000.0,
            grt=40000.0,
            year_built=2015,
        )

        mock_fetch.return_value = [
            make_synthetic_row(
                IMO="9000030",
                MMSI="211000030",
                CALLSIGN="",
                DWT="0",
                GRT="0.0",
                YEAR_BUILT="",
            )
        ]
        call_command("ingest_expected_arrivals", mode="arrivals", live=True, ports=["SGSIN"])

        vessel.refresh_from_db()
        self.assertEqual(vessel.callsign, "CALL1")
        self.assertEqual(vessel.dwt, 80000.0)
        self.assertEqual(vessel.grt, 40000.0)
        self.assertEqual(vessel.year_built, 2015)

    # 8. Exclusions: MMSI "99...", excluded vessel type, and name fallback
    @patch("apps.common.management.commands.ingest_expected_arrivals.fetch_expected_arrivals")
    def test_exclusions(self, mock_fetch):
        # Direct service check for aid to navigation MMSI 99
        from services.vessel_service import upsert_vessel
        v_aids, status_aids = upsert_vessel({"mmsi": "992110001", "name": "BUOY LIGHT 1"})
        self.assertIsNone(v_aids)
        self.assertEqual(status_aids, "excluded")

        mock_fetch.return_value = [
            # Excluded type from settings.VESSEL_TYPE_EXCLUSIONS ("Tug")
            make_synthetic_row(IMO="9000042", MMSI="211000042", TYPE_NAME="Tug"),
            # Name fallback: Unknown type with PILOT keyword from settings.VESSEL_NAME_EXCLUSION_KEYWORDS
            make_synthetic_row(IMO="9000043", MMSI="211000043", TYPE_NAME="Unknown", SHIPNAME="PILOT BOAT ONE"),
        ]

        out = StringIO()
        call_command(
            "ingest_expected_arrivals",
            mode="arrivals",
            live=True,
            ports=["SGSIN"],
            stdout=out,
        )

        self.assertEqual(Vessel.objects.filter(imo__in=["9000042", "9000043"]).count(), 0)
        self.assertEqual(VesselObservation.objects.count(), 0)
        self.assertIn("Excluded by vessel filter: 2", out.getvalue())

    # 9. Opportunity rules
    @patch("apps.common.management.commands.ingest_expected_arrivals.fetch_expected_arrivals")
    def test_opportunity_rules(self, mock_fetch):
        now = datetime.now(timezone.utc)

        # Inbound within 24h -> zone 24h
        r_24h = make_synthetic_row(
            IMO="9000051",
            MMSI="211000051",
            ETA_CALC=(now + timedelta(hours=10)).strftime("%Y-%m-%dT%H:%M:%S"),
            CURRENT_PORT="",
            NEXT_PORT_ID="290",
        )
        # Inbound within 72h (36h) -> zone 72h
        r_72h = make_synthetic_row(
            IMO="9000052",
            MMSI="211000052",
            ETA_CALC=(now + timedelta(hours=36)).strftime("%Y-%m-%dT%H:%M:%S"),
            CURRENT_PORT="",
            NEXT_PORT_ID="290",
        )
        # Inbound beyond 72h (96h) -> skipped opportunity, but Vessel & Obs created
        r_beyond = make_synthetic_row(
            IMO="9000053",
            MMSI="211000053",
            ETA_CALC=(now + timedelta(hours=96)).strftime("%Y-%m-%dT%H:%M:%S"),
            CURRENT_PORT="",
            NEXT_PORT_ID="290",
        )
        # Inbound past ETA -> skipped opportunity, but Vessel & Obs created
        r_past = make_synthetic_row(
            IMO="9000054",
            MMSI="211000054",
            ETA_CALC=(now - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%S"),
            CURRENT_PORT="",
            NEXT_PORT_ID="290",
        )
        # Anchorage -> zone anchorage
        r_anch = make_synthetic_row(
            IMO="9000055",
            MMSI="211000055",
            CURRENT_PORT="SINGAPORE ANCH",
        )
        # In port -> skipped opportunity, but Vessel & Obs created
        r_inport = make_synthetic_row(
            IMO="9000056",
            MMSI="211000056",
            CURRENT_PORT="SINGAPORE",
        )

        mock_fetch.return_value = [r_24h, r_72h, r_beyond, r_past, r_anch, r_inport]
        call_command("ingest_expected_arrivals", mode="arrivals", live=True, ports=["SGSIN"])

        # All 6 vessels and observations created
        self.assertEqual(Vessel.objects.count(), 6)
        self.assertEqual(VesselObservation.objects.count(), 6)

        # Check opportunity zones
        opp_24h = Opportunity.objects.get(vessel__imo="9000051")
        self.assertEqual(opp_24h.zone, ZONE_24H)
        self.assertEqual(opp_24h.eta_source, "eta_calc")
        self.assertTrue(opp_24h.is_inbound)
        self.assertTrue(len(opp_24h.lead_reason) <= 200)

        opp_72h = Opportunity.objects.get(vessel__imo="9000052")
        self.assertEqual(opp_72h.zone, ZONE_72H)

        opp_anch = Opportunity.objects.get(vessel__imo="9000055")
        self.assertEqual(opp_anch.zone, ZONE_ANCHORAGE)

        # Beyond, past, and inport vessels must have NO opportunity
        self.assertFalse(Opportunity.objects.filter(vessel__imo="9000053").exists())
        self.assertFalse(Opportunity.objects.filter(vessel__imo="9000054").exists())
        self.assertFalse(Opportunity.objects.filter(vessel__imo="9000056").exists())

        # Existing anchorage opportunity is NEVER moved back to 72h
        mock_fetch.return_value = [
            make_synthetic_row(
                IMO="9000055",
                MMSI="211000055",
                ETA_CALC=(now + timedelta(hours=36)).strftime("%Y-%m-%dT%H:%M:%S"),
                CURRENT_PORT="",
                NEXT_PORT_ID="290",
            )
        ]
        call_command("ingest_expected_arrivals", mode="arrivals", live=True, ports=["SGSIN"])
        opp_anch.refresh_from_db()
        self.assertEqual(opp_anch.zone, ZONE_ANCHORAGE)

    # 10. --mode inport keeps only in_port and anchorage rows
    @patch("apps.common.management.commands.ingest_expected_arrivals.fetch_expected_arrivals")
    def test_mode_inport_keeps_only_inport_and_anchorage(self, mock_fetch):
        mock_fetch.return_value = [
            make_synthetic_row(IMO="9000061", MMSI="211000061", CURRENT_PORT="SINGAPORE"),
            make_synthetic_row(IMO="9000062", MMSI="211000062", CURRENT_PORT="SINGAPORE ANCH"),
            make_synthetic_row(IMO="9000063", MMSI="211000063", CURRENT_PORT="", NEXT_PORT_ID="290"),
        ]

        out = StringIO()
        call_command("ingest_expected_arrivals", mode="inport", live=True, ports=["SGSIN"], stdout=out)

        self.assertEqual(Vessel.objects.filter(imo__in=["9000061", "9000062"]).count(), 2)
        self.assertFalse(Vessel.objects.filter(imo="9000063").exists())
        self.assertIn("skipped (not in port/anchorage): 1", out.getvalue())

    # 11. CallLimitError on the first port stops the run, second port is never called, failure log exists
    @patch("apps.common.management.commands.ingest_expected_arrivals.fetch_expected_arrivals")
    def test_call_limit_error_stops_run_and_logs(self, mock_fetch):
        mock_fetch.side_effect = CallLimitError("Daily limit reached", endpoint="https://services.marinetraffic.com/api/...")

        with self.assertRaises(CommandError) as ctx:
            call_command("ingest_expected_arrivals", mode="arrivals", live=True)

        self.assertIn("Provider error", str(ctx.exception))
        # fetch called only once for first port, second port never reached
        self.assertEqual(mock_fetch.call_count, 1)

        log = EnrichmentLog.objects.filter(success=False).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.port, self.port_sg)
        self.assertEqual(log.endpoint_called, "marinetraffic:expected_arrivals")
        self.assertIn("Daily limit reached", log.error_message)

    # 12. --pause-seconds pauses once between two live calls and not after the last
    @patch("time.sleep")
    @patch("apps.common.management.commands.ingest_expected_arrivals.fetch_expected_arrivals")
    def test_pause_seconds_between_calls(self, mock_fetch, mock_sleep):
        mock_fetch.return_value = []

        call_command("ingest_expected_arrivals", mode="arrivals", live=True, pause_seconds=90)

        self.assertEqual(mock_fetch.call_count, 2)
        mock_sleep.assert_called_once_with(90)

    # 13. A bad row is counted as an error and other rows are saved
    @patch("apps.common.management.commands.ingest_expected_arrivals.fetch_expected_arrivals")
    @patch("apps.common.management.commands.ingest_expected_arrivals.upsert_vessel")
    def test_bad_row_counted_as_error_and_others_saved(self, mock_upsert, mock_fetch):
        r1 = make_synthetic_row(IMO="9000071", MMSI="211000071")
        r2 = make_synthetic_row(IMO="9000072", MMSI="211000072")
        mock_fetch.return_value = [r1, r2]

        vessel_saved = Vessel.objects.create(imo="9000072", mmsi="211000072", name="Vessel 2")

        def side_effect(vessel_dict):
            if vessel_dict.get("imo") == "9000071":
                raise ValueError("Corrupted row data")
            return vessel_saved, "created"

        mock_upsert.side_effect = side_effect

        out = StringIO()
        call_command("ingest_expected_arrivals", mode="arrivals", live=True, ports=["SGSIN"], stdout=out)

        self.assertIn("Errors: 1", out.getvalue())
        self.assertIn("Observations created: 1", out.getvalue())

    # 14. A sentinel API key set in settings never appears in captured output
    @patch("apps.common.management.commands.ingest_expected_arrivals.fetch_expected_arrivals")
    def test_sentinel_api_key_never_leaked(self, mock_fetch):
        sentinel_key = "SENTINEL_SECRET_KEY_XYZZY"
        mock_fetch.side_effect = ProviderRequestError(f"Request failed at https://services.marinetraffic.com/api/expectedarrivals/{sentinel_key}")

        out = StringIO()
        err = StringIO()

        with self.settings(MARINETRAFFIC_API_KEY=sentinel_key):
            with self.assertLogs("vessel_intel", level="INFO") as captured_logs:
                try:
                    call_command(
                        "ingest_expected_arrivals",
                        mode="arrivals",
                        live=True,
                        ports=["SGSIN"],
                        stdout=out,
                        stderr=err,
                    )
                except CommandError:
                    pass

        self.assertNotIn(sentinel_key, out.getvalue())
        self.assertNotIn(sentinel_key, err.getvalue())
        for log_msg in captured_logs.output:
            self.assertNotIn(sentinel_key, log_msg)

    # 15. services/ files do not import integrations
    def test_services_do_not_import_integrations(self):
        services_dir = os.path.join(settings.BASE_DIR, "services")
        service_files = glob.glob(os.path.join(services_dir, "*.py"))
        self.assertTrue(len(service_files) > 0)

        for filepath in service_files:
            with open(filepath, "r", encoding="utf-8") as f:
                tree = ast.parse(f.read(), filename=filepath)

            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        self.assertFalse(
                            alias.name.startswith("integrations"),
                            f"{os.path.basename(filepath)} imports '{alias.name}'",
                        )
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        self.assertFalse(
                            node.module.startswith("integrations"),
                            f"{os.path.basename(filepath)} imports from '{node.module}'",
                        )
