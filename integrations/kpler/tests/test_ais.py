"""Tests for the Kpler AIS Latest client and parser. No network: requests.post is mocked.

NOTE: ``ais_latest_doc_example.json`` is the example printed in Kpler's OpenAPI
document (one vessel), NOT a real response. Rows built in these tests are
synthetic and are used only inside the test database.
"""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import requests
from django.test import SimpleTestCase, override_settings

from integrations.kpler.ais import fetch_ais_latest, get_ais_api_key
from integrations.kpler.ais_parser import classify_port_area, parse_ais_latest
from integrations.kpler.exceptions import (
    AuthenticationError,
    CallLimitError,
    KplerAccessError,
    ParameterError,
    ProviderRequestError,
)

FIXTURE = Path(__file__).parent / "fixtures" / "ais_latest_doc_example.json"
REAL_FIXTURE = Path(__file__).parent / "fixtures" / "ais_latest_real_trimmed.json"
NOW = datetime(2026, 11, 9, 12, 0, 0, tzinfo=timezone.utc)
KEY = "SENTINEL_AIS_KEY_777"


def feature(**over):
    props = {
        "vesselUid": 5001, "mmsi": 563000001, "imo": 9300001, "longitude": 103.85, "latitude": 1.2,
        "sog": 0.1, "cog": 90.0, "navStatus": 1, "vesselName": "TEST ANCHOR ONE",
        "callsign": "TST1", "flag": "SG", "vesselTypeAis": 70, "vesselType": "Bulk Carrier",
        "length": 200.0, "width": 32.0, "dwt": 80000, "grt": 45000, "destination": "SINGAPORE",
        "eta": None, "draught": 11.0, "posDt": (NOW - timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
    }
    props.update(over)
    return {"type": "Feature", "id": 1, "geometry": {"type": "Point", "coordinates": [props["longitude"], props["latitude"]]},
            "geometry_name": "positionGeometry", "properties": props}


def collection(*features):
    return {"type": "FeatureCollection", "features": list(features), "numberMatched": len(features)}


class ClassifyTests(SimpleTestCase):
    def test_rules(self):
        self.assertEqual(classify_port_area(5, 0.0, 1.0), "in_port")
        self.assertEqual(classify_port_area(1, 5.0, 1.0), "anchorage")
        self.assertEqual(classify_port_area(0, 0.5, 1.0), "anchorage")
        self.assertEqual(classify_port_area(0, 1.0, 1.0), "anchorage")
        self.assertEqual(classify_port_area(0, 8.0, 1.0), "unknown")
        self.assertEqual(classify_port_area(None, None, 1.0), "unknown")
        self.assertEqual(classify_port_area(5, 9.0, 1.0), "in_port")


class ParserTests(SimpleTestCase):
    def parse(self, payload, **kw):
        kw.setdefault("snapshot", NOW)
        return parse_ais_latest(payload, **kw)

    def test_documented_shape_is_parsed(self):
        data = json.loads(FIXTURE.read_text(encoding="utf-8"))
        r = self.parse(data, snapshot=datetime(2025, 9, 10, 16, 0, tzinfo=timezone.utc))
        self.assertEqual(r.stats["accepted"], 1)
        item = r.accepted[0]
        self.assertEqual(item["vessel"]["mmsi"], "987654321")
        self.assertEqual(item["vessel"]["imo"], "9128520")
        self.assertEqual(item["vessel"]["name"], "AVEL VAD")
        self.assertEqual(item["vessel"]["vessel_type"], "Bulk Carrier")
        self.assertEqual(item["vessel"]["ship_id"], "16")
        self.assertEqual(item["vessel"]["grt"], 62780.0)
        self.assertEqual(item["vessel"]["beam"], 12.42)
        self.assertEqual(item["observation"]["speed"], 10.2)
        self.assertEqual(item["observation"]["latitude"], 58.7598532)
        self.assertEqual(item["port_area"], "unknown")  # moving at 10 knots

    def test_anchored_moored_moving(self):
        r = self.parse(collection(
            feature(mmsi=1, vesselName="A", navStatus=1, sog=0.0),
            feature(mmsi=2, vesselName="B", navStatus=5, sog=0.0),
            feature(mmsi=3, vesselName="C", navStatus=0, sog=9.0),
        ))
        areas = {i["vessel"]["mmsi"]: i["port_area"] for i in r.accepted}
        self.assertEqual(areas, {"1": "anchorage", "2": "in_port", "3": "unknown"})
        self.assertEqual((r.stats["in_anchorage"], r.stats["moored"], r.stats["moving"]), (1, 1, 1))

    def test_rejections(self):
        old = (NOW - timedelta(hours=30)).isoformat().replace("+00:00", "Z")
        r = self.parse(collection(
            feature(mmsi=None),
            feature(mmsi=10, posDt=old),
            feature(mmsi=11, posDt=None),
            feature(mmsi=12, grt=500),
            feature(mmsi=13, grt=900000),
            {"type": "Feature", "geometry": None, "properties": {"mmsi": 14, "posDt": NOW.isoformat()}},
            "not a feature",
        ), gt_min=3000, gt_max=500000)
        self.assertEqual(r.stats["accepted"], 0)
        reasons = r.stats["rejection_reasons"]
        self.assertEqual(reasons["missing_mmsi"], 1)
        self.assertEqual(reasons["stale_position"], 1)
        self.assertEqual(reasons["no_position_time"], 1)
        self.assertEqual(reasons["outside_gt_range"], 2)
        self.assertEqual(reasons["bad_position"], 1)
        self.assertEqual(reasons["bad_feature"], 1)

    def test_unknown_grt_is_kept(self):
        r = self.parse(collection(feature(mmsi=20, grt=None)), gt_min=3000, gt_max=500000)
        self.assertEqual(r.stats["accepted"], 1)
        self.assertIsNone(r.accepted[0]["vessel"]["grt"])

    def test_duplicate_mmsi_keeps_newest(self):
        newer = (NOW - timedelta(minutes=5)).isoformat().replace("+00:00", "Z")
        r = self.parse(collection(feature(mmsi=30, sog=0.0), feature(mmsi=30, sog=7.0, posDt=newer)))
        self.assertEqual(len(r.accepted), 1)
        self.assertEqual(r.accepted[0]["observation"]["speed"], 7.0)

    def test_bad_imo_and_future_eta(self):
        future = (NOW + timedelta(hours=10)).isoformat().replace("+00:00", "Z")
        r = self.parse(collection(feature(mmsi=40, imo=0, eta=future), feature(mmsi=41, imo=123, eta="2020-01-01T00:00:00Z")))
        by = {i["vessel"]["mmsi"]: i for i in r.accepted}
        self.assertIsNone(by["40"]["vessel"]["imo"])
        self.assertEqual(by["40"]["lead"]["eta_source"], "ais_eta")
        self.assertEqual(by["40"]["lead"]["hours_to_eta"], 10.0)
        self.assertIsNone(by["41"]["vessel"]["imo"])
        self.assertIsNone(by["41"]["lead"]["eta"])

    def test_input_not_mutated_and_junk_payloads(self):
        payload = collection(feature(mmsi=50))
        before = json.dumps(payload, sort_keys=True)
        self.parse(payload)
        self.assertEqual(json.dumps(payload, sort_keys=True), before)
        for junk in (None, [], {}, {"features": None}, "x"):
            self.assertEqual(self.parse(junk).stats["accepted"], 0)


class RealResponseTests(SimpleTestCase):
    """ais_latest_real_trimmed.json holds 4 UNMODIFIED vessels from a real Singapore response."""

    def test_real_features_parse(self):
        data = json.loads(REAL_FIXTURE.read_text(encoding="utf-8"))
        snap = datetime(2026, 11, 9, 5, 48, tzinfo=timezone.utc)
        r = parse_ais_latest(data, snapshot=snap, gt_min=3000, gt_max=500000)
        self.assertEqual(r.stats["accepted"], 4)
        by = {i["vessel"]["name"]: i for i in r.accepted}
        self.assertEqual(by["OXALIS DAISY"]["port_area"], "anchorage")
        self.assertEqual(by["OXALIS DAISY"]["vessel"]["imo"], "1031355")
        self.assertEqual(by["OXALIS DAISY"]["vessel"]["grt"], 6011.0)
        self.assertEqual(by["KARABAKH"]["port_area"], "in_port")
        self.assertEqual(by["ATLANTIC CHALLENGER"]["port_area"], "unknown")
        jolly = by["JOLLY ROSLEE"]
        self.assertEqual(jolly["port_area"], "anchorage")  # navStatus 15 but speed 0.2
        self.assertIsNone(jolly["vessel"]["imo"])          # imo is null in the real data
        self.assertIsNone(jolly["vessel"]["grt"])          # size unknown for small craft
        self.assertEqual(jolly["observation"]["navigational_status"], 15)
        self.assertEqual(jolly["observation"]["destination"], "")


def response(status=200, body=None, text=""):
    r = MagicMock()
    r.status_code = status
    r.text = text or json.dumps(body or {})
    r.json.return_value = body if body is not None else {}
    return r


@override_settings(KPLER_API_KEY=KEY, KPLER_AIS_API_KEY="", KPLER_AIS_URL="https://example.test/ais")
class ClientTests(SimpleTestCase):
    def test_key_fallback(self):
        self.assertEqual(get_ais_api_key(), KEY)
        with self.settings(KPLER_AIS_API_KEY="OWN_AIS_KEY"):
            self.assertEqual(get_ais_api_key(), "OWN_AIS_KEY")

    @patch("integrations.kpler.ais.save_raw_response")
    @patch("integrations.kpler.ais.requests.post")
    def test_request_shape_and_key_only_in_header(self, post, save):
        post.return_value = response(200, collection(feature()))
        out = fetch_ais_latest("BBOX(position, 103, 1, 104, 2)", limit=50, label="x")
        self.assertEqual(len(out["features"]), 1)
        args, kwargs = post.call_args
        self.assertEqual(args[0], "https://example.test/ais")
        self.assertEqual(kwargs["headers"]["Authorization"], f"Basic {KEY}")
        self.assertEqual(kwargs["json"], {"filter": "BBOX(position, 103, 1, 104, 2)", "format": "json", "limit": 50})
        self.assertNotIn(KEY, json.dumps(kwargs["json"]))
        self.assertNotIn(KEY, args[0])
        save.assert_called_once()
        self.assertNotIn(KEY, json.dumps(save.call_args[0]))

    @patch("integrations.kpler.ais.requests.post")
    def test_errors_map_to_exceptions(self, post):
        cases = [(401, AuthenticationError), (403, KplerAccessError), (429, CallLimitError),
                 (400, ParameterError), (500, ProviderRequestError)]
        for status, exc in cases:
            post.return_value = response(status, text=f"bad {KEY}")
            with self.assertRaises(exc) as ctx:
                fetch_ais_latest("dwt >= 1")
            self.assertNotIn(KEY, str(ctx.exception))

    @patch("integrations.kpler.ais.requests.post")
    def test_network_error_is_sanitized(self, post):
        post.side_effect = requests.exceptions.ConnectionError(f"failed host key={KEY}")
        with self.assertRaises(ProviderRequestError) as ctx:
            fetch_ais_latest("dwt >= 1")
        self.assertNotIn(KEY, str(ctx.exception))
        self.assertIn("{api_key}", str(ctx.exception))

    @patch("integrations.kpler.ais.requests.post")
    def test_bad_body_shapes(self, post):
        bad = response(200)
        bad.json.side_effect = ValueError("no json")
        post.return_value = bad
        with self.assertRaises(ProviderRequestError):
            fetch_ais_latest("dwt >= 1")
        post.return_value = response(200, {"nope": 1})
        with self.assertRaises(ProviderRequestError):
            fetch_ais_latest("dwt >= 1")

    def test_missing_key_or_filter(self):
        with self.settings(KPLER_API_KEY="", KPLER_AIS_API_KEY=""):
            with self.assertRaises(ValueError):
                fetch_ais_latest("dwt >= 1")
        with self.assertRaises(ValueError):
            fetch_ais_latest("   ")
