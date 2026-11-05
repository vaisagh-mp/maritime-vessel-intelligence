"""
Integration tests for the scoring engine — verifies that scoring triggers
fire correctly from the service layer and don't break existing behavior.
"""
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from apps.common.constants import STAGE_DETECTED
from apps.ports.models import Port
from apps.vessels.models import Vessel
from apps.opportunities.models import Opportunity
from services.opportunity_service import (
    get_or_create_open_opportunity,
    update_opportunity_eta,
)
from services.scoring_service import calculate_score


def _port(**overrides):
    defaults = dict(
        name="Fujairah", un_locode="AEFJR", latitude=25.12, longitude=56.34,
        anchorage_latitude=25.15, anchorage_longitude=56.40, geofence_radius_km=45,
    )
    defaults.update(overrides)
    return Port.objects.create(**defaults)


def _vessel(**overrides):
    defaults = dict(mmsi="777888999", name="INTEGRATION TEST VESSEL", vessel_type="Bulk Carrier")
    defaults.update(overrides)
    return Vessel.objects.create(**defaults)


class GetOrCreateScoringTests(TestCase):
    """Score is computed immediately when a new Opportunity is created via
    get_or_create_open_opportunity."""

    def test_new_opportunity_has_score_greater_than_zero(self):
        vessel = _vessel()
        port = _port()
        opp, created = get_or_create_open_opportunity(vessel, port)
        self.assertTrue(created)
        self.assertGreater(opp.score, 0)

    def test_score_matches_calculate_score(self):
        vessel = _vessel()
        port = _port()
        opp, created = get_or_create_open_opportunity(vessel, port)
        expected = calculate_score(opp)
        self.assertEqual(opp.score, expected)


class UpdateEtaScoringTests(TestCase):
    """Score is recalculated when update_opportunity_eta changes zone/eta."""

    def test_score_increases_with_near_eta(self):
        vessel = _vessel()
        port = _port()
        opp, _ = get_or_create_open_opportunity(vessel, port, zone="72h")
        initial_score = opp.score

        # Set ETA to 12h from now (should move to 24h zone → higher ETA signal).
        near_eta = timezone.now() + timedelta(hours=12)
        update_opportunity_eta(opp, near_eta)

        # Score should increase (zone moved from 72h to 24h).
        opp.refresh_from_db()
        self.assertGreater(opp.score, initial_score)

    def test_zone_changes_on_eta_update(self):
        vessel = _vessel()
        port = _port()
        opp, _ = get_or_create_open_opportunity(vessel, port)
        self.assertEqual(opp.zone, "anchorage")

        # Set ETA to 48h from now → should move to 72h zone.
        far_eta = timezone.now() + timedelta(hours=60)
        update_opportunity_eta(opp, far_eta)
        opp.refresh_from_db()
        self.assertEqual(opp.zone, "72h")


class DedupRegressionTests(TestCase):
    """Scoring must not break the dedup guarantee: one open Opportunity per
    vessel+port combination."""

    def test_no_duplicate_open_opportunity(self):
        vessel = _vessel()
        port = _port()
        opp1, created1 = get_or_create_open_opportunity(vessel, port)
        opp2, created2 = get_or_create_open_opportunity(vessel, port)

        self.assertTrue(created1)
        self.assertFalse(created2)
        self.assertEqual(opp1.pk, opp2.pk)

    def test_dedup_score_is_consistent(self):
        vessel = _vessel()
        port = _port()
        opp1, _ = get_or_create_open_opportunity(vessel, port)
        opp2, _ = get_or_create_open_opportunity(vessel, port)
        self.assertEqual(opp1.score, opp2.score)


class BandPropertyTests(TestCase):
    """The model's band property is correctly derived from score."""

    def test_band_property_matches_get_band(self):
        vessel = _vessel()
        port = _port()
        opp, _ = get_or_create_open_opportunity(vessel, port)
        from services.scoring_service import get_band
        self.assertEqual(opp.band, get_band(opp.score))
