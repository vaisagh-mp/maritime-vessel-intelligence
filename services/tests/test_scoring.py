"""
Unit tests for services/scoring_service.py — one test per scoring signal,
plus boundary tests for ETA zones and band mapping.
"""
from datetime import timedelta

from django.test import TestCase, override_settings
from django.utils import timezone

from apps.common.constants import (
    STAGE_CONTACTED,
    STAGE_DETECTED,
    STAGE_LOST,
    STAGE_NEGOTIATION,
    STAGE_QUOTE_REQUESTED,
    STAGE_QUOTED,
    STAGE_REPLIED,
    STAGE_WON,
)
from apps.companies.models import Company
from apps.opportunities.models import Opportunity
from apps.ports.models import Port
from apps.relationships.models import VesselRelationship
from apps.vessels.models import Vessel
from services.scoring_service import calculate_score, get_band


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _port(**overrides):
    defaults = dict(
        name="Fujairah", un_locode="AEFJR", latitude=25.12, longitude=56.34,
        anchorage_latitude=25.15, anchorage_longitude=56.40, geofence_radius_km=45,
    )
    defaults.update(overrides)
    return Port.objects.create(**defaults)


def _vessel(**overrides):
    defaults = dict(mmsi="999000111", name="TEST VESSEL")
    defaults.update(overrides)
    return Vessel.objects.create(**defaults)


def _opportunity(vessel, port, **overrides):
    defaults = dict(zone="anchorage", stage=STAGE_DETECTED)
    defaults.update(overrides)
    return Opportunity.objects.create(vessel=vessel, port=port, **defaults)


# ---------------------------------------------------------------------------
# ETA / Zone signal tests
# ---------------------------------------------------------------------------

class EtaZoneSignalTests(TestCase):
    def setUp(self):
        self.port = _port()
        self.vessel = _vessel(vessel_type="Unknown Type")

    def test_anchorage_zone_scores_30(self):
        opp = _opportunity(self.vessel, self.port, zone="anchorage")
        score = calculate_score(opp)
        self.assertGreaterEqual(score, 30)

    def test_anchorage_bound_zone_scores_25(self):
        opp = _opportunity(self.vessel, self.port, zone="anchorage_bound")
        score = calculate_score(opp)
        self.assertGreaterEqual(score, 25)

    def test_24h_zone_scores_15(self):
        opp = _opportunity(self.vessel, self.port, zone="24h")
        score = calculate_score(opp)
        self.assertGreaterEqual(score, 15)

    def test_72h_zone_no_eta_scores_5(self):
        opp = _opportunity(self.vessel, self.port, zone="72h", eta=None)
        score = calculate_score(opp)
        self.assertGreaterEqual(score, 5)

    def test_72h_zone_eta_within_24h_scores_15(self):
        eta = timezone.now() + timedelta(hours=12)
        opp = _opportunity(self.vessel, self.port, zone="72h", eta=eta)
        score = calculate_score(opp)
        self.assertGreaterEqual(score, 15)

    def test_72h_zone_eta_at_exactly_24h(self):
        eta = timezone.now() + timedelta(hours=24)
        opp = _opportunity(self.vessel, self.port, zone="72h", eta=eta)
        score = calculate_score(opp)
        self.assertGreaterEqual(score, 15)

    def test_72h_zone_eta_between_24h_and_48h_scores_10(self):
        eta = timezone.now() + timedelta(hours=36)
        opp = _opportunity(self.vessel, self.port, zone="72h", eta=eta)
        score = calculate_score(opp)
        self.assertGreaterEqual(score, 10)

    def test_72h_zone_eta_at_exactly_48h(self):
        eta = timezone.now() + timedelta(hours=48)
        opp = _opportunity(self.vessel, self.port, zone="72h", eta=eta)
        score = calculate_score(opp)
        self.assertGreaterEqual(score, 10)

    def test_72h_zone_eta_between_48h_and_72h_scores_5(self):
        eta = timezone.now() + timedelta(hours=60)
        opp = _opportunity(self.vessel, self.port, zone="72h", eta=eta)
        score = calculate_score(opp)
        self.assertGreaterEqual(score, 5)

    def test_72h_zone_eta_at_exactly_72h(self):
        eta = timezone.now() + timedelta(hours=72)
        opp = _opportunity(self.vessel, self.port, zone="72h", eta=eta)
        score = calculate_score(opp)
        self.assertGreaterEqual(score, 5)


# ---------------------------------------------------------------------------
# Vessel segment signal tests
# ---------------------------------------------------------------------------

class VesselSegmentSignalTests(TestCase):
    def setUp(self):
        self.port = _port()

    def test_exact_match_adds_20(self):
        vessel = _vessel(vessel_type="Bulk Carrier")
        opp = _opportunity(vessel, self.port)
        score = calculate_score(opp)
        # anchorage zone (30) + exact segment (20) = 50
        self.assertEqual(score, 50)

    def test_keyword_match_adds_10(self):
        for vt in ["Oil/Chemical Tanker", "Heavy Load Carrier", "Ro-Ro Cargo Ship", "RoRo Vessel", "General Cargo Ship"]:
            vessel = _vessel(mmsi=f"999{hash(vt) % 1000000:06d}", vessel_type=vt)
            opp = _opportunity(vessel, self.port)
            score = calculate_score(opp)
            # anchorage zone (30) + keyword match (10) = 40
            self.assertEqual(score, 40, f"Failed for {vt}")

    def test_no_match_adds_nothing(self):
        vessel = _vessel(vessel_type="Fishing Vessel")
        opp = _opportunity(vessel, self.port)
        score = calculate_score(opp)
        # anchorage zone (30) only
        self.assertEqual(score, 30)

    def test_exact_takes_precedence_over_keyword(self):
        # "Container Ship" is both an exact match (+20) and contains "Container" keyword (+10).
        # Exact should win (+20).
        vessel = _vessel(vessel_type="Container Ship")
        opp = _opportunity(vessel, self.port)
        score = calculate_score(opp)
        # anchorage zone (30) + exact (20) = 50
        self.assertEqual(score, 50)

    def test_empty_type_adds_nothing(self):
        vessel = _vessel(vessel_type="")
        opp = _opportunity(vessel, self.port)
        score = calculate_score(opp)
        self.assertEqual(score, 30)  # just the zone signal


# ---------------------------------------------------------------------------
# Priority manager signal
# ---------------------------------------------------------------------------

class PriorityManagerSignalTests(TestCase):
    def setUp(self):
        self.port = _port()
        self.vessel = _vessel()

    def test_high_priority_manager_adds_20(self):
        company = Company.objects.create(name="Top Manager", company_type="manager", priority="high")
        VesselRelationship.objects.create(
            vessel=self.vessel, company=company, role="manager", source="test"
        )
        opp = _opportunity(self.vessel, self.port)
        score = calculate_score(opp)
        self.assertIn(20, self._signal_breakdown(opp))

    def test_medium_priority_manager_no_bonus(self):
        company = Company.objects.create(name="Mid Manager", company_type="manager", priority="medium")
        VesselRelationship.objects.create(
            vessel=self.vessel, company=company, role="manager", source="test"
        )
        opp = _opportunity(self.vessel, self.port)
        score = calculate_score(opp)
        # Only anchorage zone (30)
        self.assertEqual(score, 30)

    def test_owner_not_manager_no_bonus(self):
        company = Company.objects.create(name="Owner Co", company_type="owner", priority="high")
        VesselRelationship.objects.create(
            vessel=self.vessel, company=company, role="owner", source="test"
        )
        opp = _opportunity(self.vessel, self.port)
        score = calculate_score(opp)
        self.assertEqual(score, 30)

    def _signal_breakdown(self, opp):
        """Helper — returns a list of individual signal scores."""
        from services.scoring_service import (
            _score_eta_zone, _score_vessel_segment, _score_priority_manager,
            _score_existing_relationship, _score_verified_contact,
            _score_previous_enquiry, _score_large_fleet, _score_recent_negative,
        )
        return [
            _score_eta_zone(opp),
            _score_vessel_segment(opp.vessel),
            _score_priority_manager(opp.vessel),
            _score_existing_relationship(opp.vessel, opp),
            _score_verified_contact(opp.vessel),
            _score_previous_enquiry(opp.vessel, opp),
            _score_large_fleet(opp.vessel),
            _score_recent_negative(opp.vessel, opp),
        ]


# ---------------------------------------------------------------------------
# Existing relationship signal
# ---------------------------------------------------------------------------

class ExistingRelationshipSignalTests(TestCase):
    def setUp(self):
        self.port = _port()
        self.vessel = _vessel()
        self.company = Company.objects.create(name="Shared Co", company_type="manager")
        VesselRelationship.objects.create(
            vessel=self.vessel, company=self.company, role="manager", source="test"
        )

    def test_won_prior_opp_adds_30(self):
        # Another vessel linked to the same company has a won Opportunity.
        other_vessel = _vessel(mmsi="888000222", name="SISTER SHIP")
        VesselRelationship.objects.create(
            vessel=other_vessel, company=self.company, role="manager", source="test"
        )
        _opportunity(other_vessel, self.port, stage=STAGE_WON)

        opp = _opportunity(self.vessel, self.port)
        from services.scoring_service import _score_existing_relationship
        self.assertEqual(_score_existing_relationship(self.vessel, opp), 30)

    def test_active_pipeline_prior_opp_adds_20(self):
        other_vessel = _vessel(mmsi="888000333", name="ANOTHER SHIP")
        VesselRelationship.objects.create(
            vessel=other_vessel, company=self.company, role="manager", source="test"
        )
        _opportunity(other_vessel, self.port, stage=STAGE_CONTACTED)

        opp = _opportunity(self.vessel, self.port)
        from services.scoring_service import _score_existing_relationship
        self.assertEqual(_score_existing_relationship(self.vessel, opp), 20)

    def test_no_prior_opps_adds_0(self):
        opp = _opportunity(self.vessel, self.port)
        from services.scoring_service import _score_existing_relationship
        self.assertEqual(_score_existing_relationship(self.vessel, opp), 0)


# ---------------------------------------------------------------------------
# Verified contact signal
# ---------------------------------------------------------------------------

class VerifiedContactSignalTests(TestCase):
    def setUp(self):
        self.port = _port()
        self.vessel = _vessel()
        self.company = Company.objects.create(name="VCo", company_type="manager")

    def test_verified_relationship_adds_20(self):
        VesselRelationship.objects.create(
            vessel=self.vessel, company=self.company, role="manager",
            source="test", verified=True,
        )
        opp = _opportunity(self.vessel, self.port)
        from services.scoring_service import _score_verified_contact
        self.assertEqual(_score_verified_contact(self.vessel), 20)

    def test_unverified_adds_0(self):
        VesselRelationship.objects.create(
            vessel=self.vessel, company=self.company, role="manager",
            source="test", verified=False,
        )
        opp = _opportunity(self.vessel, self.port)
        from services.scoring_service import _score_verified_contact
        self.assertEqual(_score_verified_contact(self.vessel), 0)


# ---------------------------------------------------------------------------
# Previous enquiry signal
# ---------------------------------------------------------------------------

class PreviousEnquirySignalTests(TestCase):
    def setUp(self):
        self.port = _port()
        self.vessel = _vessel()

    def test_prior_quote_requested_adds_25(self):
        _opportunity(self.vessel, self.port, stage=STAGE_QUOTE_REQUESTED)
        opp = _opportunity(self.vessel, _port(un_locode="SGSIN", name="Singapore"))
        from services.scoring_service import _score_previous_enquiry
        self.assertEqual(_score_previous_enquiry(self.vessel, opp), 25)

    def test_no_prior_quote_adds_0(self):
        _opportunity(self.vessel, self.port, stage=STAGE_CONTACTED)
        opp = _opportunity(self.vessel, _port(un_locode="SGSIN", name="Singapore"))
        from services.scoring_service import _score_previous_enquiry
        self.assertEqual(_score_previous_enquiry(self.vessel, opp), 0)


# ---------------------------------------------------------------------------
# Large fleet / DWT signal
# ---------------------------------------------------------------------------

class LargeFleetSignalTests(TestCase):
    def setUp(self):
        self.port = _port()

    def test_large_grt_adds_15(self):
        vessel = _vessel(grt=50000)
        opp = _opportunity(vessel, self.port)
        from services.scoring_service import _score_large_fleet
        self.assertEqual(_score_large_fleet(vessel), 15)

    def test_medium_grt_adds_12(self):
        vessel = _vessel(grt=25000)
        opp = _opportunity(vessel, self.port)
        from services.scoring_service import _score_large_fleet
        self.assertEqual(_score_large_fleet(vessel), 12)

    def test_small_grt_adds_0(self):
        vessel = _vessel(grt=2500)
        opp = _opportunity(vessel, self.port)
        from services.scoring_service import _score_large_fleet
        self.assertEqual(_score_large_fleet(vessel), 0)

    def test_null_grt_adds_0(self):
        vessel = _vessel(grt=None)
        from services.scoring_service import _score_large_fleet
        self.assertEqual(_score_large_fleet(vessel), 0)


# ---------------------------------------------------------------------------
# Recent negative signal
# ---------------------------------------------------------------------------

class RecentNegativeSignalTests(TestCase):
    def setUp(self):
        self.port = _port()
        self.vessel = _vessel()

    def test_recent_lost_subtracts_20(self):
        lost_opp = _opportunity(self.vessel, self.port, stage=STAGE_LOST)
        new_opp = _opportunity(self.vessel, _port(un_locode="SGSIN", name="Singapore"))
        from services.scoring_service import _score_recent_negative
        self.assertEqual(_score_recent_negative(self.vessel, new_opp), -20)

    def test_old_lost_no_penalty(self):
        lost_opp = _opportunity(self.vessel, self.port, stage=STAGE_LOST)
        # Backdate the updated_at beyond the window
        Opportunity.objects.filter(pk=lost_opp.pk).update(
            updated_at=timezone.now() - timedelta(days=100)
        )
        new_opp = _opportunity(self.vessel, _port(un_locode="SGSIN", name="Singapore"))
        from services.scoring_service import _score_recent_negative
        self.assertEqual(_score_recent_negative(self.vessel, new_opp), 0)


# ---------------------------------------------------------------------------
# Negative clamp
# ---------------------------------------------------------------------------

class NegativeClampTests(TestCase):
    def setUp(self):
        self.port = _port()
        self.vessel = _vessel(vessel_type="Fishing Vessel", dwt=1000)

    def test_score_never_goes_below_zero(self):
        """Even with a recent negative and no positive signals beyond zone,
        score is clamped to 0."""
        # Create a lost opportunity to trigger the -20 signal
        _opportunity(self.vessel, self.port, stage=STAGE_LOST)
        # Create a new opportunity in 72h zone (only +10)
        new_opp = _opportunity(
            self.vessel,
            _port(un_locode="SGSIN", name="Singapore"),
            zone="72h", eta=None,
        )
        score = calculate_score(new_opp)
        self.assertEqual(score, 0)

    def test_previous_lost_does_not_trigger_previous_enquiry_bonus(self):
        """Part F: STAGE_LOST only gets -20 penalty, never +25 previous enquiry bonus."""
        from services.scoring_service import _score_previous_enquiry, _score_recent_negative
        _opportunity(self.vessel, self.port, stage=STAGE_LOST)
        new_opp = _opportunity(self.vessel, _port(un_locode="SGSIN", name="Singapore"))
        self.assertEqual(_score_previous_enquiry(self.vessel, new_opp), 0)
        self.assertEqual(_score_recent_negative(self.vessel, new_opp), -20)


# ---------------------------------------------------------------------------
# Combined signals
# ---------------------------------------------------------------------------

class CombinedSignalsTests(TestCase):
    def test_multiple_signals_stack(self):
        port = _port()
        vessel = _vessel(vessel_type="Bulk Carrier", dwt=82000, grt=50000)
        company = Company.objects.create(name="Big Manager", company_type="manager", priority="high")
        VesselRelationship.objects.create(
            vessel=vessel, company=company, role="manager", source="test", verified=True,
        )
        opp = _opportunity(vessel, port, zone="anchorage")

        score = calculate_score(opp)
        # anchorage (30) + exact segment (20) + priority manager (20)
        # + verified contact (20) + size GRT (15) = 105, capped at 100
        self.assertEqual(score, 100)


# ---------------------------------------------------------------------------
# Band mapping boundary tests
# ---------------------------------------------------------------------------

class BandMappingTests(TestCase):
    def test_exactly_80_is_hot(self):
        self.assertEqual(get_band(80), "HOT")

    def test_79_is_high(self):
        self.assertEqual(get_band(79), "HIGH")

    def test_exactly_60_is_high(self):
        self.assertEqual(get_band(60), "HIGH")

    def test_59_is_medium(self):
        self.assertEqual(get_band(59), "MEDIUM")

    def test_exactly_40_is_medium(self):
        self.assertEqual(get_band(40), "MEDIUM")

    def test_39_is_low(self):
        self.assertEqual(get_band(39), "LOW")

    def test_0_is_low(self):
        self.assertEqual(get_band(0), "LOW")

    def test_100_is_hot(self):
        self.assertEqual(get_band(100), "HOT")

    def test_200_is_hot(self):
        self.assertEqual(get_band(200), "HOT")
