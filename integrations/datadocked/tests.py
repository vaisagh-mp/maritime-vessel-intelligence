from django.test import TestCase

from .parsers import parse_eta_utc, parse_management_response, parse_vessels_by_area


class ParserTests(TestCase):
    def test_parse_vessels_by_area(self):
        payload = {"vessels": [{"mmsi": "1", "name": "X"}]}
        self.assertEqual(len(parse_vessels_by_area(payload)), 1)
        self.assertEqual(parse_vessels_by_area({}), [])

    def test_parse_eta_utc(self):
        dt = parse_eta_utc("Aug 09, 2026 05:51 UTC")
        self.assertEqual((dt.year, dt.month, dt.day, dt.hour, dt.minute), (2026, 8, 9, 5, 51))
        self.assertIsNone(parse_eta_utc(""))
        self.assertIsNone(parse_eta_utc(None))
        self.assertIsNone(parse_eta_utc("garbage"))

    def test_parse_management_response_dash_is_none(self):
        payload = {
            "imo": "1", "mmsi": "2",
            "management": {
                "manager": "VERITAL MARINE SERVICES LLC",
                "managerEmail": "vmsinfo@verital.ae",
                "registeredOwner": "-",
                "registeredOwnerEmail": "-",
            },
        }
        parsed = parse_management_response(payload)
        self.assertEqual(parsed["manager_name"], "VERITAL MARINE SERVICES LLC")
        self.assertIsNone(parsed["registered_owner_name"])
        self.assertIsNone(parsed["registered_owner_email"])
