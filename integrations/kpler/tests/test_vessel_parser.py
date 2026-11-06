"""Unit tests for Kpler vessel node parser."""
import json
from pathlib import Path
from unittest import TestCase

from apps.common.constants import (
    RELATIONSHIP_ROLE_BENEFICIAL_OWNER,
    RELATIONSHIP_ROLE_COMMERCIAL_MANAGER,
    RELATIONSHIP_ROLE_ISM_MANAGER,
    RELATIONSHIP_ROLE_OPERATOR,
    RELATIONSHIP_ROLE_OWNER,
    RELATIONSHIP_ROLE_REGISTERED_OWNER,
    RELATIONSHIP_ROLE_TECHNICAL_MANAGER,
)
from integrations.kpler.vessel_parser import parse_vessel_node


class VesselParserTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        fixture_path = Path(__file__).parent / "fixtures" / "kpler_sample.json"
        with open(fixture_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        cls.nodes = {
            node["identifier"]["imo"]: node
            for node in data["data"]["vessels"]["nodes"]
        }

    def test_vessel_1_pacific_explorer(self):
        """Vessel 1: Technical and ISM manager with website & email."""
        node = self.nodes["9146297"]
        parsed = parse_vessel_node(node)

        self.assertEqual(parsed["imo"], "9146297")
        particulars = parsed["particulars"]
        self.assertEqual(particulars["name"], "PACIFIC EXPLORER")
        self.assertEqual(particulars["mmsi"], "240123000")
        self.assertEqual(particulars["callsign"], "SXYZ")
        self.assertEqual(particulars["ship_id"], "1001")
        self.assertEqual(particulars["flag"], "Greece")
        self.assertEqual(particulars["vessel_type"], "Bulk Carrier")
        self.assertEqual(particulars["vessel_size_segment"], "Handymax")
        self.assertEqual(particulars["year_built"], 1998)
        self.assertEqual(particulars["grt"], 28000.0)
        self.assertEqual(particulars["dwt"], 48000.0)
        self.assertEqual(particulars["length"], 189.9)
        self.assertEqual(particulars["beam"], 32.2)
        self.assertEqual(particulars["draught"], 12.5)
        self.assertEqual(particulars["last_dry_dock"], "2023-05-15")
        self.assertEqual(particulars["last_renewal_survey"], "2023-05-20")

        parties = parsed["parties"]
        self.assertEqual(len(parties), 6)
        roles = {p["role"]: p for p in parties}

        tech = roles[RELATIONSHIP_ROLE_TECHNICAL_MANAGER]
        self.assertEqual(tech["name"], "Pacific Shipmanagement Ltd")
        self.assertEqual(tech["country"], "Cyprus")
        self.assertEqual(tech["website"], "https://pacificshipmanagement.com")
        self.assertEqual(tech["email"], "tech@pacificshipmanagement.com")

        ism = roles[RELATIONSHIP_ROLE_ISM_MANAGER]
        self.assertEqual(ism["name"], "Pacific Shipmanagement Ltd")
        self.assertEqual(ism["email"], "ism@pacificshipmanagement.com")

        owner = roles[RELATIONSHIP_ROLE_REGISTERED_OWNER]
        self.assertEqual(owner["name"], "Pacific Maritime Ltd")
        self.assertEqual(owner["email"], "owner@pacificmaritime.com")

        comm = roles[RELATIONSHIP_ROLE_COMMERCIAL_MANAGER]
        self.assertEqual(comm["name"], "Global Chartering Inc")

        op = roles[RELATIONSHIP_ROLE_OPERATOR]
        self.assertEqual(op["name"], "Pacific Operations SA")

        bene = roles[RELATIONSHIP_ROLE_BENEFICIAL_OWNER]
        self.assertEqual(bene["name"], "Pacific Holdings Corp")

    def test_vessel_2_nordic_star(self):
        """Vessel 2: Technical manager with NO website or email."""
        node = self.nodes["9308766"]
        parsed = parse_vessel_node(node)

        self.assertEqual(parsed["imo"], "9308766")
        self.assertEqual(parsed["particulars"]["name"], "NORDIC STAR")
        self.assertEqual(parsed["particulars"]["grt"], 58000.0)
        self.assertEqual(parsed["particulars"]["dwt"], 105000.0)

        parties = parsed["parties"]
        roles = {p["role"]: p for p in parties}

        self.assertIn(RELATIONSHIP_ROLE_TECHNICAL_MANAGER, roles)
        tech = roles[RELATIONSHIP_ROLE_TECHNICAL_MANAGER]
        self.assertEqual(tech["name"], "Bergen Marine AS")
        self.assertIsNone(tech["website"])
        self.assertIsNone(tech["email"])

        self.assertIn(RELATIONSHIP_ROLE_OWNER,
    RELATIONSHIP_ROLE_REGISTERED_OWNER, roles)
        owner = roles[RELATIONSHIP_ROLE_REGISTERED_OWNER]
        self.assertEqual(owner["name"], "Nordic Tankers KS")
        self.assertIsNone(owner["email"])

    def test_vessel_3_eastern_phoenix(self):
        """Vessel 3: Registered owner with email, test email lowercasing."""
        node = self.nodes["9456789"]
        parsed = parse_vessel_node(node)

        self.assertEqual(parsed["imo"], "9456789")
        parties = parsed["parties"]
        roles = {p["role"]: p for p in parties}

        self.assertIn(RELATIONSHIP_ROLE_OWNER,
    RELATIONSHIP_ROLE_REGISTERED_OWNER, roles)
        owner = roles[RELATIONSHIP_ROLE_REGISTERED_OWNER]
        self.assertEqual(owner["name"], "Phoenix Shipping Lines Co")
        self.assertEqual(owner["website"], "https://phoenixshipping.pa")
        self.assertEqual(owner["email"], "registry@phoenixshipping.pa")  # Lowercased

    def test_vessel_4_sea_breeze(self):
        """Vessel 4: Several null roles, null callsign/shipId."""
        node = self.nodes["9876543"]
        parsed = parse_vessel_node(node)

        self.assertEqual(parsed["imo"], "9876543")
        self.assertIsNone(parsed["particulars"]["callsign"])
        self.assertIsNone(parsed["particulars"]["ship_id"])
        self.assertIsNone(parsed["particulars"]["vessel_size_segment"])
        self.assertEqual(len(parsed["parties"]), 0)

    def test_missing_roles_and_null_current(self):
        node = {
            "identifier": {"imo": "9999999"},
            "management": {
                "technicalManager": None,
                "ismManager": {"current": None},
                "registeredOwner": {"current": {"name": ""}},
                "beneficialOwner": {},
            },
        }
        parsed = parse_vessel_node(node)
        self.assertEqual(parsed["imo"], "9999999")
        self.assertEqual(parsed["parties"], [])

    def test_malformed_numbers(self):
        node = {
            "identifier": {"imo": "1234567"},
            "particulars": {
                "hull": {"yearOfBuild": "not-a-year"},
                "dimension": {"lengthOverall": -10, "breadthExtreme": 0, "draught": "abc"},
                "tonnage": {"grossTonnage": "invalid", "deadweightTonnage": "-500"},
            },
        }
        parsed = parse_vessel_node(node)
        particulars = parsed["particulars"]
        self.assertIsNone(particulars["year_built"])
        self.assertIsNone(particulars["length"])
        self.assertIsNone(particulars["beam"])
        self.assertIsNone(particulars["draught"])
        self.assertIsNone(particulars["grt"])
        self.assertIsNone(particulars["dwt"])

    def test_empty_node(self):
        parsed = parse_vessel_node({})
        self.assertIsNone(parsed["imo"])
        self.assertEqual(parsed["parties"], [])
        self.assertIsNone(parsed["particulars"]["name"])

        parsed_none = parse_vessel_node(None)
        self.assertIsNone(parsed_none["imo"])
        self.assertEqual(parsed_none["parties"], [])

