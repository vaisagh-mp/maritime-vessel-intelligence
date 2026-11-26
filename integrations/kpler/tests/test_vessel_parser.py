"""Unit tests for Kpler vessel node parser."""
import json
from pathlib import Path
from unittest import TestCase

from apps.common.constants import (
    RELATIONSHIP_ROLE_BENEFICIAL_OWNER,
    RELATIONSHIP_ROLE_COMMERCIAL_MANAGER,
    RELATIONSHIP_ROLE_ISM_MANAGER,
    RELATIONSHIP_ROLE_OPERATOR,
    RELATIONSHIP_ROLE_REGISTERED_OWNER,
    RELATIONSHIP_ROLE_TECHNICAL_MANAGER,
)
from integrations.kpler.vessel_parser import parse_vessel_node


class VesselParserTests(TestCase):
    """Parser tests against REAL Kpler data (4 vessels trimmed, unmodified, from
    Kpler's own sample file: kpler_sample_trimmed.json)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        fixture_path = Path(__file__).parent / "fixtures" / "kpler_sample_trimmed.json"
        with open(fixture_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        # Kpler sends the IMO as a number in the raw node; key by string.
        cls.nodes = {
            str(node["identifier"]["imo"]): node
            for node in data["data"]["vessels"]["nodes"]
        }

    @staticmethod
    def _by_role(parsed):
        return {p["role"]: p for p in parsed["parties"]}

    def test_fixture_holds_the_four_real_vessels(self):
        self.assertEqual(set(self.nodes), {"9146297", "9308766", "9294848", "9250218"})

    def test_blpl_faith_managers_have_website_and_email(self):
        """IMO 9146297: technical and ISM manager with website and email."""
        parsed = parse_vessel_node(self.nodes["9146297"])
        self.assertEqual(parsed["imo"], "9146297")

        particulars = parsed["particulars"]
        self.assertEqual(particulars["name"], "BLPL FAITH")
        self.assertEqual(particulars["mmsi"], "370014000")
        self.assertEqual(particulars["flag"], "Panama")
        self.assertEqual(particulars["vessel_type"], "Container")
        self.assertEqual(particulars["vessel_size_segment"], "Feeder")
        self.assertEqual(particulars["year_built"], 1997)
        self.assertEqual(particulars["grt"], 8299.0)
        self.assertEqual(particulars["dwt"], 10299.0)
        self.assertIsNone(particulars["last_dry_dock"])

        parties = parsed["parties"]
        self.assertEqual(len(parties), 6)
        roles = self._by_role(parsed)

        for role in (
            RELATIONSHIP_ROLE_TECHNICAL_MANAGER,
            RELATIONSHIP_ROLE_ISM_MANAGER,
            RELATIONSHIP_ROLE_COMMERCIAL_MANAGER,
            RELATIONSHIP_ROLE_OPERATOR,
        ):
            self.assertEqual(roles[role]["name"], "PROVIDENCE SHIP MANAGEMENT INDIA PVT LTD")
            self.assertEqual(roles[role]["country"], "INDIA")
            self.assertTrue(roles[role]["website"])
            self.assertEqual(roles[role]["email"], "enquiry@tgsprovidence.com")

        self.assertEqual(roles[RELATIONSHIP_ROLE_REGISTERED_OWNER]["name"], "BLPL SINGAPORE PTE LTD")
        self.assertEqual(roles[RELATIONSHIP_ROLE_REGISTERED_OWNER]["email"], "info@tgsblpl.com")
        self.assertEqual(
            roles[RELATIONSHIP_ROLE_BENEFICIAL_OWNER]["name"],
            "TRANSWORLD HOLDINGS LTD TRANSWORLD GROUP",
        )

    def test_kanha_technical_manager_has_no_contacts(self):
        """IMO 9308766: technical and ISM manager ONTARIO MARINE SERVICES with no
        website and no email; registered owner and commercial manager have an email."""
        parsed = parse_vessel_node(self.nodes["9308766"])
        self.assertEqual(parsed["imo"], "9308766")
        self.assertEqual(parsed["particulars"]["name"], "KANHA")
        self.assertEqual(parsed["particulars"]["mmsi"], "511101460")
        self.assertEqual(parsed["particulars"]["grt"], 8351.0)
        self.assertEqual(parsed["particulars"]["dwt"], 12887.0)
        self.assertEqual(parsed["particulars"]["last_dry_dock"], "2025-08-30")

        roles = self._by_role(parsed)
        self.assertEqual(
            set(roles),
            {
                RELATIONSHIP_ROLE_REGISTERED_OWNER,
                RELATIONSHIP_ROLE_COMMERCIAL_MANAGER,
                RELATIONSHIP_ROLE_TECHNICAL_MANAGER,
                RELATIONSHIP_ROLE_ISM_MANAGER,
            },
        )
        for role in (RELATIONSHIP_ROLE_TECHNICAL_MANAGER, RELATIONSHIP_ROLE_ISM_MANAGER):
            self.assertEqual(roles[role]["name"], "ONTARIO MARINE SERVICES")
            self.assertIsNone(roles[role]["website"])
            self.assertIsNone(roles[role]["email"])

        owner = roles[RELATIONSHIP_ROLE_REGISTERED_OWNER]
        self.assertEqual(owner["name"], "KANHA SHIPPING INC")
        self.assertEqual(owner["email"], "kanhashippinginc@gmail.com")
        self.assertIsNone(owner["website"])

    def test_wan_hai_501_managers_have_contacts(self):
        parsed = parse_vessel_node(self.nodes["9294848"])
        self.assertEqual(parsed["particulars"]["name"], "WAN HAI 501")
        self.assertEqual(parsed["particulars"]["flag"], "Singapore")
        self.assertEqual(parsed["particulars"]["grt"], 42532.0)
        roles = self._by_role(parsed)
        tech = roles[RELATIONSHIP_ROLE_TECHNICAL_MANAGER]
        self.assertEqual(tech["name"], "WAN HAI LINES SINGAPORE PTE")
        self.assertEqual(tech["website"], "https://www.wanhai.com/")
        self.assertEqual(tech["email"], "adm_dept@wanhai.com")
        # Operator and beneficial owner are a different company (the parent)
        self.assertEqual(roles[RELATIONSHIP_ROLE_OPERATOR]["name"], "WAN HAI LINES LTD")
        self.assertEqual(roles[RELATIONSHIP_ROLE_BENEFICIAL_OWNER]["name"], "WAN HAI LINES LTD")

    def test_bailian_star_one_company_without_contacts_in_five_roles(self):
        parsed = parse_vessel_node(self.nodes["9250218"])
        self.assertEqual(parsed["particulars"]["name"], "BAILIAN STAR")
        self.assertEqual(parsed["particulars"]["vessel_size_segment"], "Panamax")
        parties = parsed["parties"]
        self.assertEqual(len(parties), 5)
        self.assertEqual({p["name"] for p in parties}, {"BAILIAN STAR SHIPPING LTD"})
        self.assertTrue(all(p["website"] is None and p["email"] is None for p in parties))
        # No commercial manager in Kpler's data for this vessel
        self.assertNotIn(RELATIONSHIP_ROLE_COMMERCIAL_MANAGER, self._by_role(parsed))

    def test_emails_are_lowercased(self):
        node = {
            "identifier": {"imo": 1234567},
            "management": {
                "technicalManager": {"current": {"name": "X", "email": "  Ops@Example.COM "}},
            },
        }
        parsed = parse_vessel_node(node)
        self.assertEqual(parsed["parties"][0]["email"], "ops@example.com")

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

