"""Tests for the ingest_ais_latest command. Provider access is mocked; data is synthetic test data."""
import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from apps.common.constants import SOURCE_KPLER_AIS_LATEST
from apps.enrichment.models import EnrichmentLog
from apps.observations.models import VesselObservation
from apps.opportunities.models import Opportunity
from apps.ports.models import Port
from apps.vessels.models import Vessel
from integrations.kpler.exceptions import CallLimitError

FETCH = "apps.common.management.commands.ingest_ais_latest.fetch_ais_latest"
KEY = "SENTINEL_AIS_KEY_555"


def feature(mmsi, **over):
    now = datetime.now(timezone.utc)
    props = {
        "vesselUid": mmsi, "mmsi": mmsi, "imo": int(f"93{str(mmsi)[-5:]}"), "longitude": 103.85, "latitude": 1.2,
        "sog": 0.0, "cog": 90.0, "navStatus": 1, "vesselName": f"SYN VESSEL {mmsi}", "callsign": "SYN",
        "flag": "SG", "vesselTypeAis": 70, "vesselType": "Bulk Carrier", "length": 200.0, "width": 32.0,
        "dwt": 80000, "grt": 45000, "destination": "SINGAPORE", "eta": None, "draught": 11.0,
        "posDt": (now - timedelta(minutes=30)).isoformat().replace("+00:00", "Z"),
    }
    props.update(over)
    return {"type": "Feature", "id": mmsi,
            "geometry": {"type": "Point", "coordinates": [props["longitude"], props["latitude"]]},
            "properties": props}


def payload(*features):
    return {"type": "FeatureCollection", "features": list(features), "numberMatched": len(features)}


@override_settings(KPLER_API_KEY=KEY, KPLER_AIS_API_KEY="")
class IngestAisLatestTests(TestCase):
    def setUp(self):
        self.port = Port.objects.create(
            name="Singapore", un_locode="SGSIN", latitude=1.29, longitude=103.85,
            anchorage_latitude=1.25, anchorage_longitude=103.8, geofence_radius_km=30.0,
            marinetraffic_port_id=290, active=True, ais_filter="BBOX(position, 103.5, 1.0, 104.2, 1.5)",
        )

    def run_cmd(self, **kw):
        out = StringIO()
        call_command("ingest_ais_latest", stdout=out, **kw)
        return out.getvalue()

    # ---- arguments ----------------------------------------------------------
    def test_requires_live_or_file(self):
        with self.assertRaises(CommandError):
            call_command("ingest_ais_latest", ports=["SGSIN"])

    def test_from_file_requires_one_port(self):
        with self.assertRaises(CommandError):
            call_command("ingest_ais_latest", from_file="x.json")

    def test_unknown_port(self):
        with self.assertRaises(CommandError):
            call_command("ingest_ais_latest", live=True, ports=["XXXXX"])

    @patch(FETCH)
    def test_empty_filter_is_refused_without_a_call(self, fetch):
        Port.objects.update(ais_filter="")
        with self.assertRaises(CommandError) as ctx:
            call_command("ingest_ais_latest", live=True, ports=["SGSIN"])
        self.assertIn("ais_filter", str(ctx.exception))
        fetch.assert_not_called()

    @patch(FETCH)
    def test_default_ports_skip_ports_without_filter(self, fetch):
        Port.objects.create(
            name="Fujairah", un_locode="AEFJR", latitude=25.1, longitude=56.3, anchorage_latitude=25.2,
            anchorage_longitude=56.4, geofence_radius_km=30.0, marinetraffic_port_id=790, active=True, ais_filter="",
        )
        fetch.return_value = payload()
        self.run_cmd(live=True)
        self.assertEqual(fetch.call_count, 1)

    # ---- ingest behaviour -----------------------------------------------------
    @patch(FETCH)
    def test_anchored_new_vessel_becomes_a_lead(self, fetch):
        fetch.return_value = payload(feature(563000001))
        out = self.run_cmd(live=True, ports=["SGSIN"])
        self.assertIn("In anchorage: 1", out)
        self.assertIn("Vessels created: 1", out)
        self.assertIn("Opportunities created: 1, updated: 0, skipped: 0", out)
        v = Vessel.objects.get(mmsi="563000001")
        self.assertEqual(v.vessel_type, "Bulk Carrier")
        self.assertEqual(v.ship_id, "563000001")
        opp = Opportunity.objects.get(vessel=v)
        self.assertEqual(opp.zone, "anchorage")
        self.assertEqual(opp.port, self.port)
        obs = VesselObservation.objects.get(vessel=v)
        self.assertEqual(obs.source, SOURCE_KPLER_AIS_LATEST)
        self.assertEqual(obs.port_area, "anchorage")
        self.assertEqual(obs.navigational_status, 1)
        self.assertEqual(EnrichmentLog.objects.filter(success=True, endpoint_called="kpler:ais_latest").count(), 1)

    @patch(FETCH)
    def test_filter_text_and_limit_are_passed_through(self, fetch):
        fetch.return_value = payload()
        self.run_cmd(live=True, ports=["SGSIN"], limit=77)
        args, kwargs = fetch.call_args
        self.assertEqual(args[0], "BBOX(position, 103.5, 1.0, 104.2, 1.5)")
        self.assertEqual(kwargs["limit"], 77)

    @patch(FETCH)
    def test_moored_or_moving_new_vessels_are_not_created(self, fetch):
        fetch.return_value = payload(feature(563000002, navStatus=5), feature(563000003, navStatus=0, sog=9.0))
        out = self.run_cmd(live=True, ports=["SGSIN"])
        self.assertIn("Not recorded (new vessel, not at anchor or size unknown): 2", out)
        self.assertFalse(Vessel.objects.exists())
        self.assertFalse(Opportunity.objects.exists())

    @patch(FETCH)
    def test_known_vessel_gets_position_but_keeps_its_name_and_type(self, fetch):
        known = Vessel.objects.create(imo="9300004", mmsi="563000004", name="MT NAME", vessel_type="Crude Oil Tanker")
        fetch.return_value = payload(feature(563000004, imo=9300004, navStatus=0, sog=11.0, vesselName="OTHER NAME"))
        out = self.run_cmd(live=True, ports=["SGSIN"])
        self.assertIn("Vessels updated: 1", out)
        self.assertIn("Observations created: 1", out)
        self.assertIn("Opportunities created: 0", out)
        known.refresh_from_db()
        self.assertEqual(known.name, "MT NAME")
        self.assertEqual(known.vessel_type, "Crude Oil Tanker")
        self.assertEqual(known.observations.count(), 1)
        self.assertFalse(Opportunity.objects.exists())

    @patch(FETCH)
    def test_known_vessel_found_by_mmsi_when_imo_differs_or_missing(self, fetch):
        Vessel.objects.create(imo=None, mmsi="563000005", name="NO IMO YET")
        fetch.return_value = payload(feature(563000005, imo=9300005, navStatus=5))
        self.run_cmd(live=True, ports=["SGSIN"])
        self.assertEqual(Vessel.objects.count(), 1)
        self.assertEqual(Vessel.objects.get().imo, "9300005")

    @patch(FETCH)
    def test_existing_lead_is_updated_and_moves_to_anchorage(self, fetch):
        v = Vessel.objects.create(imo="9300006", mmsi="563000006", name="ARRIVING", vessel_type="Bulk Carrier", grt=40000)
        Opportunity.objects.create(vessel=v, port=self.port, zone="72h", stage="detected")
        fetch.return_value = payload(feature(563000006, imo=9300006))
        out = self.run_cmd(live=True, ports=["SGSIN"])
        self.assertIn("Opportunities created: 0, updated: 1", out)
        self.assertEqual(Opportunity.objects.filter(vessel=v).count(), 1)
        self.assertEqual(Opportunity.objects.get(vessel=v).zone, "anchorage")

    @patch(FETCH)
    def test_same_position_is_not_stored_twice(self, fetch):
        fetch.return_value = payload(feature(563000007, posDt=(datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat().replace("+00:00", "Z")))
        self.run_cmd(live=True, ports=["SGSIN"])
        out = self.run_cmd(live=True, ports=["SGSIN"])
        self.assertEqual(VesselObservation.objects.count(), 1)
        self.assertIn("Observations created: 0", out)
        self.assertEqual(Opportunity.objects.count(), 1)

    @patch(FETCH)
    def test_excluded_vessel_types_are_skipped(self, fetch):
        fetch.return_value = payload(feature(563000008, vesselType="Tug"))
        out = self.run_cmd(live=True, ports=["SGSIN"])
        self.assertIn("Excluded by vessel filter: 1", out)
        self.assertFalse(Vessel.objects.exists())

    @patch(FETCH)
    def test_dry_run_changes_nothing(self, fetch):
        fetch.return_value = payload(feature(563000009))
        out = self.run_cmd(live=True, ports=["SGSIN"], dry_run=True)
        self.assertIn("DRY-RUN", out)
        self.assertIn("Vessels created: 1", out)
        self.assertFalse(Vessel.objects.exists())
        self.assertFalse(VesselObservation.objects.exists())
        self.assertFalse(Opportunity.objects.exists())

    @patch(FETCH)
    def test_bad_row_counted_and_others_saved(self, fetch):
        fetch.return_value = payload(feature(563000010), feature(563000011))
        real = __import__("services.vessel_service", fromlist=["upsert_vessel"]).upsert_vessel

        def flaky(d):
            if d["mmsi"] == "563000010":
                raise ValueError("corrupt")
            return real(d)

        with patch("apps.common.management.commands.ingest_ais_latest.upsert_vessel", side_effect=flaky):
            out = self.run_cmd(live=True, ports=["SGSIN"])
        self.assertIn("Errors: 1", out)
        self.assertEqual(Vessel.objects.count(), 1)

    @patch(FETCH)
    def test_new_anchored_vessel_without_size_is_not_created(self, fetch):
        fetch.return_value = payload(feature(563000020, grt=None), feature(563000021, grt=0))
        out = self.run_cmd(live=True, ports=["SGSIN"])
        self.assertIn("In anchorage: 2", out)
        self.assertIn("size unknown): 2", out)
        self.assertIn("Vessels created: 0", out)
        self.assertFalse(Vessel.objects.exists())
        self.assertFalse(Opportunity.objects.exists())

    @patch(FETCH)
    def test_known_vessel_with_stored_size_still_gets_a_lead_when_ais_size_missing(self, fetch):
        Vessel.objects.create(imo="9300022", mmsi="563000022", name="KNOWN", vessel_type="Bulk Carrier", grt=40000)
        fetch.return_value = payload(feature(563000022, imo=9300022, grt=None))
        out = self.run_cmd(live=True, ports=["SGSIN"])
        self.assertIn("Opportunities created: 1", out)

    @patch(FETCH)
    def test_known_vessel_with_no_size_anywhere_gets_position_but_no_lead(self, fetch):
        Vessel.objects.create(imo="9300023", mmsi="563000023", name="NO SIZE", vessel_type="Bulk Carrier")
        fetch.return_value = payload(feature(563000023, imo=9300023, grt=None))
        out = self.run_cmd(live=True, ports=["SGSIN"])
        self.assertIn("Observations created: 1", out)
        self.assertIn("Opportunities created: 0, updated: 0, skipped: 1", out)
        self.assertFalse(Opportunity.objects.exists())

    # ---- file mode ----------------------------------------------------------------
    def test_from_file_reads_raw_envelope_without_network(self):
        env = {"service": "kpler_ais", "label": "x", "saved_at": "now", "payload": payload(feature(563000012))}
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as fh:
            json.dump(env, fh)
            path = fh.name
        try:
            with patch(FETCH) as fetch:
                out = self.run_cmd(from_file=path, ports=["SGSIN"])
                fetch.assert_not_called()
        finally:
            os.unlink(path)
        self.assertIn("Vessels created: 1", out)

    # ---- errors ---------------------------------------------------------------------
    @patch(FETCH)
    def test_provider_error_is_sanitized_and_logged(self, fetch):
        fetch.side_effect = CallLimitError(f"Rate limit key={KEY}")
        with self.assertLogs("vessel_intel", level="INFO") as logs:
            with self.assertRaises(CommandError) as ctx:
                call_command("ingest_ais_latest", live=True, ports=["SGSIN"], stdout=StringIO(), stderr=StringIO())
        self.assertNotIn(KEY, str(ctx.exception))
        for line in logs.output:
            self.assertNotIn(KEY, line)
        self.assertEqual(EnrichmentLog.objects.filter(success=False, endpoint_called="kpler:ais_latest").count(), 1)

    @patch(FETCH)
    def test_missing_key(self, fetch):
        with self.settings(KPLER_API_KEY="", KPLER_AIS_API_KEY=""):
            with self.assertRaises(CommandError):
                call_command("ingest_ais_latest", live=True, ports=["SGSIN"])
        fetch.assert_not_called()
