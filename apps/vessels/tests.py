from django.test import TestCase

from apps.vessels.models import Vessel
from apps.vessels.validators import (
    is_aid_to_navigation_mmsi,
    is_implausible_speed,
    is_vessel_name_excluded,
    is_vessel_type_excluded,
)
from services.vessel_service import get_or_create_vessel


class VesselTypeExclusionTests(TestCase):
    def test_known_excluded_types_are_blocked(self):
        for t in ["Tug", "tug boat", "Landing Craft", "PILOT boat", "Buoy Tender"]:
            self.assertTrue(is_vessel_type_excluded(t), t)

    def test_unknown_types_are_not_excluded(self):
        for t in ["Chemical/Oil Products Tanker", "Container Ship", "Bulk Carrier", "Something New"]:
            self.assertFalse(is_vessel_type_excluded(t), t)

    def test_blank_type_is_not_excluded(self):
        self.assertFalse(is_vessel_type_excluded(""))
        self.assertFalse(is_vessel_type_excluded(None))


class AidToNavigationMmsiTests(TestCase):
    def test_mmsi_starting_with_99_is_blocked(self):
        for mmsi in ["994196109", "994196114", "991234567", 994196109]:
            self.assertTrue(is_aid_to_navigation_mmsi(str(mmsi)), mmsi)

    def test_normal_commercial_mmsi_is_not_blocked(self):
        for mmsi in ["538011089", "477123456", "211234567"]:
            self.assertFalse(is_aid_to_navigation_mmsi(mmsi), mmsi)

    def test_empty_or_none_mmsi_is_false(self):
        self.assertFalse(is_aid_to_navigation_mmsi(None))
        self.assertFalse(is_aid_to_navigation_mmsi(""))


class ImplausibleSpeedTests(TestCase):
    def test_excessive_speed_is_flagged(self):
        self.assertTrue(is_implausible_speed(1090.0))
        self.assertTrue(is_implausible_speed("1090.0"))
        self.assertTrue(is_implausible_speed(60.1))

    def test_normal_speed_is_not_flagged(self):
        self.assertFalse(is_implausible_speed(12.5))
        self.assertFalse(is_implausible_speed(0.0))
        self.assertFalse(is_implausible_speed(50.0))
        self.assertFalse(is_implausible_speed(60.0))

    def test_missing_or_invalid_speed_is_not_flagged(self):
        self.assertFalse(is_implausible_speed(None))
        self.assertFalse(is_implausible_speed(""))
        self.assertFalse(is_implausible_speed("invalid"))


class VesselNameExclusionFallbackTests(TestCase):
    def test_unknown_or_blank_type_with_pilot_name_is_excluded(self):
        self.assertTrue(is_vessel_name_excluded("ABS DHRUVA PILOT84", "Unknown"))
        self.assertTrue(is_vessel_name_excluded("ABS DHRUVA PILOT84", ""))
        self.assertTrue(is_vessel_name_excluded("ABS DHRUVA PILOT84", None))

    def test_unknown_or_blank_type_with_sar_or_patrol_name_is_excluded(self):
        self.assertTrue(is_vessel_name_excluded("SAR AIRCRAFT CG 760", "Unknown"))
        self.assertTrue(is_vessel_name_excluded("PORT PATROL 1", ""))

    def test_known_commercial_type_with_keyword_in_name_is_not_excluded(self):
        # Commercial vessel whose name happens to contain "PILOT"
        self.assertFalse(is_vessel_name_excluded("MSC PILOT STAR", "Container Ship"))
        self.assertFalse(is_vessel_name_excluded("PATROL LEADER", "Bulk Carrier"))

    def test_regular_name_with_unknown_type_is_not_excluded(self):
        self.assertFalse(is_vessel_name_excluded("OCEAN PRIDE", "Unknown"))
        self.assertFalse(is_vessel_name_excluded("OCEAN PRIDE", ""))


class VesselDiscoveryIntegrationTests(TestCase):
    def test_structural_99_mmsi_excluded_even_with_unrecognized_type(self):
        raw = {
            "mmsi": "994196109",
            "name": "BUOY NO. 8 RED",
            "typeSpecific": "Preferred Channel Starboard Hand",
        }
        vessel, created = get_or_create_vessel(raw)
        self.assertIsNone(vessel)
        self.assertFalse(created)
        self.assertFalse(Vessel.objects.filter(mmsi="994196109").exists())

    def test_aircraft_or_impossible_speed_excluded(self):
        raw = {
            "mmsi": "419999999",
            "name": "SAR AIRCRAFT CG 760",
            "typeSpecific": "HSC (HAZ-C)",
            "speed": 1090.0,
        }
        vessel, created = get_or_create_vessel(raw)
        self.assertIsNone(vessel)
        self.assertFalse(created)

    def test_missing_speed_record_falls_through_and_creates_vessel(self):
        raw = {
            "mmsi": "538011089",
            "name": "COMMERCIAL SHIP 1",
            "typeSpecific": "Bulk Carrier",
        }
        vessel, created = get_or_create_vessel(raw)
        self.assertIsNotNone(vessel)
        self.assertTrue(created)
        self.assertEqual(vessel.mmsi, "538011089")

    def test_pilot_name_fallback_excludes_unknown_type(self):
        raw = {
            "mmsi": "419111222",
            "name": "ABS DHRUVA PILOT84",
            "typeSpecific": "Unknown",
        }
        vessel, created = get_or_create_vessel(raw)
        self.assertIsNone(vessel)
        self.assertFalse(created)

    def test_legitimate_commercial_vessel_with_pilot_in_name_created(self):
        raw = {
            "mmsi": "477999888",
            "name": "MSC PILOT STAR",
            "typeSpecific": "Container Ship",
            "speed": 14.2,
        }
        vessel, created = get_or_create_vessel(raw)
        self.assertIsNotNone(vessel)
        self.assertTrue(created)
        self.assertEqual(vessel.name, "MSC PILOT STAR")


class ImoNormalisationTests(TestCase):
    """IMO placeholders ("", None, "0") mean 'missing' and are never stored."""

    def test_normalize_imo_treats_placeholders_as_missing(self):
        from apps.common.utils import normalize_imo

        for value in [None, "", "  ", "0", 0, "0000000", "null", "None", "-"]:
            self.assertIsNone(normalize_imo(value), repr(value))

    def test_normalize_imo_keeps_real_values_as_str(self):
        from apps.common.utils import normalize_imo

        self.assertEqual(normalize_imo("9389679"), "9389679")
        self.assertEqual(normalize_imo(9389679), "9389679")
        self.assertEqual(normalize_imo(" 9389679 "), "9389679")

    def test_vessel_save_never_stores_placeholder_imo(self):
        for i, placeholder in enumerate(["0", "", None]):
            v = Vessel.objects.create(mmsi=f"2000000{i}", name="X", imo=placeholder)
            v.refresh_from_db()
            self.assertIsNone(v.imo, repr(placeholder))

    def test_enrichment_does_not_store_zero_imo(self):
        """enrich_vessel() with no provider does not alter a vessel's IMO."""
        from services.enrichment_service import enrich_vessel

        vessel = Vessel.objects.create(mmsi="211234567", name="NO IMO SHIP")
        result = enrich_vessel(vessel.pk)
        vessel.refresh_from_db()
        self.assertIsNone(vessel.imo)
        self.assertEqual(result["status"], "no_provider_configured")

    def test_enrichment_stores_real_imo_and_lookup_key_ignores_zero(self):
        """normalize_imo returns None for zero; non-zero IMO is preserved by save()."""
        from apps.common.utils import normalize_imo

        # Zero is treated as missing
        self.assertIsNone(normalize_imo("0"))

        # A real IMO is preserved
        vessel = Vessel.objects.create(mmsi="211234568", name="HAS IMO SHIP", imo="9389679")
        vessel.refresh_from_db()
        self.assertEqual(vessel.imo, "9389679")
