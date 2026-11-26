"""
integrations/kpler/tests/test_arrivals_parser.py

Unit tests for Expected Arrivals parser and cleaning rules (Step 5).
Uses pure synthetic fixtures; tests all cleaning rules, identity rejection,
port area classification, ETA logic, lead hints, and immutability.
"""

import ast
import json
import os
import sys
import unittest
from copy import deepcopy
from datetime import datetime, timedelta, timezone

from integrations.kpler.arrivals_parser import ParseResult, parse_arrivals

SINGAPORE_PORT = {
    "port_id": "290",
    "unlocode": "SGSIN",
    "home_names": ["SINGAPORE"],
}

FUJAIRAH_PORT = {
    "port_id": "790",
    "unlocode": "AEFJR",
    "home_names": ["FUJAIRAH"],
}


def make_row(**overrides):
    """Helper to generate a valid synthetic row for arrivals testing."""
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
        "DRAUGHT": "120",  # decimetres -> 12.0 m
        "LAT": "1.2500",
        "LON": "103.8000",
        "SPEED": "125",    # deciknots -> 12.5 knots
        "COURSE": "180.0",
        "STATUS": "0",
        "NEXT_PORT_NAME": "SINGAPORE",
        "NEXT_PORT_ID": "290",
        "NEXT_PORT_UNLOCODE": "SGSIN",
        "ETA_CALC": "2026-11-05T12:00:00",
        "ETA": "2026-11-05T14:00:00",
        "ETA_UPDATED": "2026-11-04T08:00:00",
        "LAST_PORT": "PORT KLANG",
        "LAST_PORT_UNLOCODE": "MYPKG",
        "LAST_PORT_TIME": "2026-11-02T10:00:00",
        "CURRENT_PORT": "",
        "TIMESTAMP": "2026-11-04T12:00:00",
    }
    base.update(overrides)
    return base


class TestArrivalsParser(unittest.TestCase):
    """Test suite for Expected Arrivals parser."""

    def setUp(self):
        self.snapshot = datetime(2026, 11, 4, 12, 0, 0, tzinfo=timezone.utc)

    def test_empty_list_returns_empty_result(self):
        """An empty rows list returns an empty ParseResult with zero stats."""
        result = parse_arrivals([], port=SINGAPORE_PORT)
        self.assertIsInstance(result, ParseResult)
        self.assertEqual(result.accepted, [])
        self.assertEqual(result.rejected, [])
        self.assertEqual(result.stats["raw_rows"], 0)
        self.assertEqual(result.stats["accepted"], 0)
        self.assertEqual(result.stats["rejected"], 0)
        self.assertIsNone(result.stats["snapshot"])

    def test_string_to_number_conversion_and_zero_handling(self):
        """Verify string conversion and that '0', '0.0', or empty becomes None for dimensions."""
        row = make_row(
            GRT="0",
            DWT="0.0",
            LENGTH="",
            WIDTH="0",
            DRAUGHT="0",
            YEAR_BUILT="0",
            SPEED="0",    # Speed 0 is valid for moored/anchored vessels
            COURSE="0",
            STATUS="0",
        )
        result = parse_arrivals([row], port=SINGAPORE_PORT, snapshot=self.snapshot)
        self.assertEqual(len(result.accepted), 1)
        vessel = result.accepted[0]["vessel"]
        obs = result.accepted[0]["observation"]

        self.assertIsNone(vessel["grt"])
        self.assertIsNone(vessel["dwt"])
        self.assertIsNone(vessel["length"])
        self.assertIsNone(vessel["beam"])
        self.assertIsNone(vessel["draught"])
        self.assertIsNone(vessel["year_built"])

        self.assertEqual(obs["speed"], 0.0)
        self.assertEqual(obs["course"], 0.0)
        self.assertEqual(obs["navigational_status"], 0)

    def test_speed_and_draught_scaling(self):
        """Rule 3: SPEED is knots x 10, DRAUGHT is metres x 10."""
        row = make_row(SPEED="145", DRAUGHT="135")
        result = parse_arrivals([row], port=SINGAPORE_PORT, snapshot=self.snapshot)
        self.assertEqual(len(result.accepted), 1)
        self.assertEqual(result.accepted[0]["observation"]["speed"], 14.5)
        self.assertEqual(result.accepted[0]["vessel"]["draught"], 13.5)

    def test_future_year_built(self):
        """Rule 4: YEAR_BUILT > snapshot.year sets year_built to None and adds flag."""
        row_future = make_row(YEAR_BUILT="2028")
        row_valid = make_row(IMO="9000002", MMSI="211000002", YEAR_BUILT="2026")

        result = parse_arrivals([row_future, row_valid], port=SINGAPORE_PORT, snapshot=self.snapshot)
        self.assertEqual(len(result.accepted), 2)

        future_item = result.accepted[0]
        self.assertIsNone(future_item["vessel"]["year_built"])
        self.assertIn("year_built_future", future_item["flags"])

        valid_item = result.accepted[1]
        self.assertEqual(valid_item["vessel"]["year_built"], 2026)
        self.assertNotIn("year_built_future", valid_item["flags"])

    def test_rejection_invalid_imo(self):
        """Rule 6: IMO stripped must be exactly 7 digits."""
        rows = [
            make_row(IMO="12345"),        # 5 digits
            make_row(IMO="12345678"),     # 8 digits
            make_row(IMO="ABC1234"),      # Letters
            make_row(IMO=""),             # Empty
        ]
        result = parse_arrivals(rows, port=SINGAPORE_PORT, snapshot=self.snapshot)
        self.assertEqual(len(result.accepted), 0)
        self.assertEqual(len(result.rejected), 4)
        for rej in result.rejected:
            self.assertEqual(rej["reason"], "invalid_imo")
        self.assertEqual(result.stats["rejection_reasons"]["invalid_imo"], 4)

    def test_rejection_invalid_mmsi(self):
        """Rule 7: MMSI must be 9 digits starting with 2 to 7."""
        rows = [
            make_row(MMSI="123456789"),   # Starts with 1
            make_row(MMSI="823456789"),   # Starts with 8
            make_row(MMSI="923456789"),   # Starts with 9
            make_row(MMSI="2110000"),     # 7 digits
            make_row(MMSI="2110000000"),  # 10 digits
        ]
        result = parse_arrivals(rows, port=SINGAPORE_PORT, snapshot=self.snapshot)
        self.assertEqual(len(result.accepted), 0)
        self.assertEqual(len(result.rejected), 5)
        for rej in result.rejected:
            self.assertEqual(rej["reason"], "invalid_mmsi")
        self.assertEqual(result.stats["rejection_reasons"]["invalid_mmsi"], 5)

    def test_rejection_no_position(self):
        """Rule 8: Missing or non-numeric LAT/LON rejects with no_position."""
        rows = [
            make_row(LAT="", LON="103.8"),
            make_row(LAT="1.25", LON=""),
            make_row(LAT="not_a_num", LON="103.8"),
            make_row(LAT=None, LON=None),
        ]
        result = parse_arrivals(rows, port=SINGAPORE_PORT, snapshot=self.snapshot)
        self.assertEqual(len(result.accepted), 0)
        self.assertEqual(len(result.rejected), 4)
        for rej in result.rejected:
            self.assertEqual(rej["reason"], "no_position")
        self.assertEqual(result.stats["rejection_reasons"]["no_position"], 4)

    def test_rejection_stale_position_cutoff(self):
        """
        Rule 9: TIMESTAMP more than 24h before snapshot is rejected as stale_position.
        Exactly 24h is kept; 24h + 1m is rejected.
        """
        # Exactly 24h prior: 2026-11-03 12:00:00 (snapshot is 2026-11-04 12:00:00)
        row_exact_24h = make_row(IMO="9000001", MMSI="211000001", TIMESTAMP="2026-11-03T12:00:00")
        # 24h + 1m prior: 2026-11-03 11:59:00
        row_stale_24h_1m = make_row(IMO="9000002", MMSI="211000002", TIMESTAMP="2026-11-03T11:59:00")

        result = parse_arrivals([row_exact_24h, row_stale_24h_1m], port=SINGAPORE_PORT, snapshot=self.snapshot)
        self.assertEqual(len(result.accepted), 1)
        self.assertEqual(result.accepted[0]["vessel"]["imo"], "9000001")

        self.assertEqual(len(result.rejected), 1)
        self.assertEqual(result.rejected[0]["reason"], "stale_position")
        self.assertEqual(result.rejected[0]["imo"], "9000002")

    def test_duplicate_imo_keeps_latest_timestamp(self):
        """Rule 10: Duplicate IMOs keep the row with the latest TIMESTAMP."""
        r1 = make_row(IMO="9000001", MMSI="211000001", TIMESTAMP="2026-11-04T08:00:00", SHIPNAME="Vessel Early")
        r2 = make_row(IMO="9000001", MMSI="211000001", TIMESTAMP="2026-11-04T11:30:00", SHIPNAME="Vessel Latest")
        r3 = make_row(IMO="9000001", MMSI="211000001", TIMESTAMP="2026-11-04T09:00:00", SHIPNAME="Vessel Mid")

        result = parse_arrivals([r1, r2, r3], port=SINGAPORE_PORT, snapshot=self.snapshot)
        self.assertEqual(len(result.accepted), 1)
        self.assertEqual(result.accepted[0]["vessel"]["name"], "Vessel Latest")
        self.assertEqual(len(result.rejected), 2)
        for rej in result.rejected:
            self.assertEqual(rej["reason"], "duplicate")
            self.assertEqual(rej["imo"], "9000001")
        self.assertEqual(result.stats["raw_rows"], 3)
        self.assertEqual(result.stats["accepted"], 1)
        self.assertEqual(result.stats["rejected"], 2)

    def test_port_area_anchorage(self):
        """Rule 12: cp ends with ' ANCH' and starts with home name -> anchorage."""
        row = make_row(CURRENT_PORT="SINGAPORE ANCH")
        result = parse_arrivals([row], port=SINGAPORE_PORT, snapshot=self.snapshot)
        self.assertEqual(len(result.accepted), 1)
        item = result.accepted[0]
        self.assertEqual(item["observation"]["port_area"], "anchorage")
        self.assertFalse(item["lead"]["is_inbound"])

    def test_port_area_in_port(self):
        """Rule 12: cp equals home name -> in_port."""
        row = make_row(CURRENT_PORT="SINGAPORE")
        result = parse_arrivals([row], port=SINGAPORE_PORT, snapshot=self.snapshot)
        self.assertEqual(len(result.accepted), 1)
        item = result.accepted[0]
        self.assertEqual(item["observation"]["port_area"], "in_port")
        self.assertFalse(item["lead"]["is_inbound"])

    def test_port_area_inbound(self):
        """Rule 12: cp is empty and NEXT_PORT_ID == port_id -> inbound."""
        row = make_row(CURRENT_PORT="", NEXT_PORT_ID="290")
        result = parse_arrivals([row], port=SINGAPORE_PORT, snapshot=self.snapshot)
        self.assertEqual(len(result.accepted), 1)
        item = result.accepted[0]
        self.assertEqual(item["observation"]["port_area"], "inbound")
        self.assertTrue(item["lead"]["is_inbound"])
        self.assertNotIn("inbound_from_other_port", item["flags"])

    def test_port_area_inbound_from_other_port(self):
        """Rule 12: cp is another named port and NEXT_PORT_ID == port_id -> inbound + flag."""
        row = make_row(CURRENT_PORT="PORT KLANG", NEXT_PORT_ID="290")
        result = parse_arrivals([row], port=SINGAPORE_PORT, snapshot=self.snapshot)
        self.assertEqual(len(result.accepted), 1)
        item = result.accepted[0]
        self.assertEqual(item["observation"]["port_area"], "inbound")
        self.assertTrue(item["lead"]["is_inbound"])
        self.assertIn("inbound_from_other_port", item["flags"])

    def test_port_area_anchorage_bound(self):
        """Rule 12: cp empty, NEXT_PORT_NAME ends with ANCH, NEXT_PORT_UNLOCODE empty -> anchorage_bound."""
        row = make_row(
            CURRENT_PORT="",
            NEXT_PORT_ID="",
            NEXT_PORT_NAME="SINGAPORE ANCH",
            NEXT_PORT_UNLOCODE="",
        )
        result = parse_arrivals([row], port=SINGAPORE_PORT, snapshot=self.snapshot)
        self.assertEqual(len(result.accepted), 1)
        item = result.accepted[0]
        self.assertEqual(item["observation"]["port_area"], "anchorage_bound")
        self.assertFalse(item["lead"]["is_inbound"])

    def test_port_area_unknown(self):
        """Rule 12: Anything else -> unknown."""
        row = make_row(CURRENT_PORT="ROTTERDAM", NEXT_PORT_ID="999", NEXT_PORT_NAME="ROTTERDAM")
        result = parse_arrivals([row], port=SINGAPORE_PORT, snapshot=self.snapshot)
        self.assertEqual(len(result.accepted), 1)
        item = result.accepted[0]
        self.assertEqual(item["observation"]["port_area"], "unknown")
        self.assertFalse(item["lead"]["is_inbound"])

    def test_eta_calc_preferred(self):
        """Rule 13: ETA_CALC is preferred when present."""
        row = make_row(
            ETA_CALC="2026-11-06T10:00:00",
            ETA="2026-11-06T18:00:00",
        )
        result = parse_arrivals([row], port=SINGAPORE_PORT, snapshot=self.snapshot)
        item = result.accepted[0]
        expected_eta = datetime(2026, 11, 6, 10, 0, 0, tzinfo=timezone.utc)
        self.assertEqual(item["lead"]["eta"], expected_eta)
        self.assertEqual(item["lead"]["eta_source"], "eta_calc")
        self.assertNotIn("eta_from_ais_only", item["flags"])

    def test_eta_ais_fallback(self):
        """Rule 13: If ETA_CALC is empty but ETA present, use ETA with ais_eta and flag."""
        row = make_row(
            ETA_CALC="",
            ETA="2026-11-06T18:00:00",
        )
        result = parse_arrivals([row], port=SINGAPORE_PORT, snapshot=self.snapshot)
        item = result.accepted[0]
        expected_eta = datetime(2026, 11, 6, 18, 0, 0, tzinfo=timezone.utc)
        self.assertEqual(item["lead"]["eta"], expected_eta)
        self.assertEqual(item["lead"]["eta_source"], "ais_eta")
        self.assertIn("eta_from_ais_only", item["flags"])

    def test_eta_both_empty(self):
        """Rule 13: If both ETAs are empty, eta is None and eta_source is empty string."""
        row = make_row(ETA_CALC="", ETA="")
        result = parse_arrivals([row], port=SINGAPORE_PORT, snapshot=self.snapshot)
        item = result.accepted[0]
        self.assertIsNone(item["lead"]["eta"])
        self.assertEqual(item["lead"]["eta_source"], "")
        self.assertIsNone(item["lead"]["hours_to_eta"])

    def test_eta_in_past(self):
        """Rule 14: Chosen ETA earlier than snapshot is cleared, flagged eta_in_past, kept."""
        row = make_row(ETA_CALC="2026-11-04T08:00:00")  # Snapshot is 12:00:00 same day
        result = parse_arrivals([row], port=SINGAPORE_PORT, snapshot=self.snapshot)
        self.assertEqual(len(result.accepted), 1)
        item = result.accepted[0]
        self.assertIsNone(item["lead"]["eta"])
        self.assertEqual(item["lead"]["eta_source"], "")
        self.assertIn("eta_in_past", item["flags"])
        self.assertIsNone(item["lead"]["hours_to_eta"])

    def test_eta_beyond_window(self):
        """Rule 15: Chosen ETA > window_days is kept and flagged eta_beyond_window."""
        # 15 days ahead (window is 14 days)
        beyond_dt = self.snapshot + timedelta(days=15)
        row = make_row(ETA_CALC=beyond_dt.strftime("%Y-%m-%dT%H:%M:%S"))
        result = parse_arrivals([row], port=SINGAPORE_PORT, snapshot=self.snapshot, window_days=14)
        item = result.accepted[0]
        self.assertEqual(item["lead"]["eta"], beyond_dt)
        self.assertIn("eta_beyond_window", item["flags"])
        self.assertIsNotNone(item["lead"]["hours_to_eta"])

    def test_hours_to_eta_calculation(self):
        """Rule 17: hours_to_eta is rounded to 1 decimal."""
        # 12.5 hours ahead
        future_dt = self.snapshot + timedelta(hours=12, minutes=30)
        row = make_row(ETA_CALC=future_dt.strftime("%Y-%m-%dT%H:%M:%S"))
        result = parse_arrivals([row], port=SINGAPORE_PORT, snapshot=self.snapshot)
        item = result.accepted[0]
        self.assertEqual(item["lead"]["hours_to_eta"], 12.5)

    def test_last_port_is_same_port(self):
        """Rule 18: True when LAST_PORT_UNLOCODE == unlocode or LAST_PORT starts with home name."""
        row_unlocode = make_row(IMO="9000001", MMSI="211000001", LAST_PORT="ANYWHERE", LAST_PORT_UNLOCODE="SGSIN")
        row_home_name = make_row(IMO="9000002", MMSI="211000002", LAST_PORT="SINGAPORE ANCH", LAST_PORT_UNLOCODE="")
        row_different = make_row(IMO="9000003", MMSI="211000003", LAST_PORT="PORT KLANG", LAST_PORT_UNLOCODE="MYPKG")

        result = parse_arrivals([row_unlocode, row_home_name, row_different], port=SINGAPORE_PORT, snapshot=self.snapshot)
        self.assertTrue(result.accepted[0]["lead"]["last_port_is_same_port"])
        self.assertTrue(result.accepted[1]["lead"]["last_port_is_same_port"])
        self.assertFalse(result.accepted[2]["lead"]["last_port_is_same_port"])

    def test_came_from_target_port(self):
        """Rule 19: UNLOCODE of other_ports matching LAST_PORT_UNLOCODE or LAST_PORT name."""
        other_ports = [FUJAIRAH_PORT]

        # Case A: matching UNLOCODE
        r1 = make_row(IMO="9000001", MMSI="211000001", LAST_PORT="FUJAIRAH", LAST_PORT_UNLOCODE="AEFJR")
        # Case B: matching name ending in " ANCH" without UNLOCODE
        r2 = make_row(IMO="9000002", MMSI="211000002", LAST_PORT="FUJAIRAH ANCH", LAST_PORT_UNLOCODE="")
        # Case C: non-matching port
        r3 = make_row(IMO="9000003", MMSI="211000003", LAST_PORT="SHANGHAI", LAST_PORT_UNLOCODE="CNSHA")

        result = parse_arrivals([r1, r2, r3], port=SINGAPORE_PORT, snapshot=self.snapshot, other_ports=other_ports)
        self.assertEqual(result.accepted[0]["lead"]["came_from_target_port"], "AEFJR")
        self.assertEqual(result.accepted[1]["lead"]["came_from_target_port"], "AEFJR")
        self.assertIsNone(result.accepted[2]["lead"]["came_from_target_port"])

    def test_default_snapshot_from_max_timestamp(self):
        """When snapshot is omitted, the default is the maximum TIMESTAMP across input rows."""
        r1 = make_row(IMO="9000001", MMSI="211000001", TIMESTAMP="2026-11-04T10:00:00")
        r2 = make_row(IMO="9000002", MMSI="211000002", TIMESTAMP="2026-11-04T16:00:00")
        r3 = make_row(IMO="9000003", MMSI="211000003", TIMESTAMP="2026-11-04T14:00:00")

        result = parse_arrivals([r1, r2, r3], port=SINGAPORE_PORT)
        expected_snapshot_iso = "2026-11-04T16:00:00+00:00"
        self.assertEqual(result.stats["snapshot"], expected_snapshot_iso)

    def test_input_immutability(self):
        """parse_arrivals must never modify its input rows or dictionaries."""
        rows = [
            make_row(IMO="9000001", MMSI="211000001"),
            make_row(IMO="9000002", MMSI="211000002"),
        ]
        rows_copy = deepcopy(rows)
        parse_arrivals(rows, port=SINGAPORE_PORT, snapshot=self.snapshot)
        self.assertEqual(rows, rows_copy)

    def test_model_field_names_conformance(self):
        """
        Confirm that observation dict uses exact VesselObservation model field names:
        'speed' (not 'speed_knots') and 'timestamp' (not 'observed_at').
        """
        row = make_row()
        result = parse_arrivals([row], port=SINGAPORE_PORT, snapshot=self.snapshot)
        obs = result.accepted[0]["observation"]

        self.assertIn("speed", obs)
        self.assertNotIn("speed_knots", obs)

        self.assertIn("timestamp", obs)
        self.assertNotIn("observed_at", obs)

    def test_imports_standard_library_only(self):
        """arrivals_parser module must only import from Python standard library."""
        import integrations.kpler.arrivals_parser as parser_module

        filepath = parser_module.__file__
        with open(filepath, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=filepath)

        imported_modules = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported_modules.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imported_modules.add(node.module.split(".")[0])

        allowed_stdlib = {
            "collections",
            "dataclasses",
            "datetime",
            "typing",
            "copy",
            "re",
            "math",
            "os",
            "sys",
        }
        disallowed = {"django", "requests", "apps", "services", "integrations"}
        for mod in imported_modules:
            self.assertNotIn(
                mod,
                disallowed,
                f"Disallowed non-standard dependency '{mod}' imported in arrivals_parser.py",
            )
            self.assertIn(
                mod,
                allowed_stdlib,
                f"Unexpected module '{mod}' imported in arrivals_parser.py",
            )

    def test_optional_smoke_test(self):
        """Optional smoke test: runs if KPLER_SMOKE_FILE points to a JSON file."""
        smoke_file = os.environ.get("KPLER_SMOKE_FILE")
        if not smoke_file or not os.path.exists(smoke_file):
            self.skipTest("KPLER_SMOKE_FILE unset or file does not exist")

        with open(smoke_file, "r", encoding="utf-8") as f:
            raw_data = json.load(f)

        if isinstance(raw_data, dict) and "data" in raw_data:
            rows = raw_data["data"]
        elif isinstance(raw_data, list):
            rows = raw_data
        else:
            self.skipTest("KPLER_SMOKE_FILE format unrecognized")

        result = parse_arrivals(rows, port=SINGAPORE_PORT)
        self.assertEqual(
            len(result.accepted) + len(result.rejected),
            result.stats["raw_rows"],
        )


if __name__ == "__main__":
    unittest.main()
