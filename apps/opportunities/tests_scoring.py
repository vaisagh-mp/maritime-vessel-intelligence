"""
Step 7 scoring tests: factor boundaries, cap/floor, band edges,
rescore management command, dedup, and zone consistency.
"""
from datetime import timedelta
import io

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from django.contrib.auth.models import Group, User

from apps.common.constants import (
    CLOSED_STAGES,
    PORT_AREA_ANCHORAGE_BOUND,
    RELATIONSHIP_ROLE_BENEFICIAL_OWNER,
    RELATIONSHIP_ROLE_COMMERCIAL_MANAGER,
    RELATIONSHIP_ROLE_ISM_MANAGER,
    RELATIONSHIP_ROLE_MANAGER,
    RELATIONSHIP_ROLE_OPERATOR,
    RELATIONSHIP_ROLE_OWNER,
    RELATIONSHIP_ROLE_TECHNICAL_MANAGER,
    STAGE_DETECTED,
    STAGE_LOST,
    STAGE_WON,
    ZONE_24H,
    ZONE_72H,
    ZONE_ANCHORAGE,
    ZONE_ANCHORAGE_BOUND,
)
from apps.companies.models import Company
from apps.observations.models import VesselObservation
from apps.opportunities.models import Opportunity, OpportunityStageChange
from apps.ports.models import Port
from apps.relationships.models import VesselRelationship
from apps.vessels.models import Vessel
from services.opportunity_service import apply_lead, get_or_create_open_opportunity
from services.scoring_service import (
    _score_origin_and_repeat,
    _score_priority_manager,
    _score_vessel_size,
    calculate_score,
    calculate_score_and_reason,
    get_band,
)


def _make_port(un_locode="AEFJR", name="Fujairah"):
    return Port.objects.create(
        name=name,
        un_locode=un_locode,
        latitude=25.12,
        longitude=56.34,
        anchorage_latitude=25.15,
        anchorage_longitude=56.40,
        geofence_radius_km=45,
    )


def _make_vessel(**kwargs):
    defaults = {"mmsi": "111222333", "name": "TEST VESSEL"}
    defaults.update(kwargs)
    return Vessel.objects.create(**defaults)


def _make_opp(vessel, port, **kwargs):
    defaults = {"zone": ZONE_ANCHORAGE, "stage": STAGE_DETECTED}
    defaults.update(kwargs)
    return Opportunity.objects.create(vessel=vessel, port=port, **defaults)


class FactorBoundaryTests(TestCase):
    def setUp(self):
        self.port = _make_port()

    # 1. GRT Boundaries
    def test_grt_2999_scores_0(self):
        v = _make_vessel(mmsi="100000001", grt=2999)
        self.assertEqual(_score_vessel_size(v), 0)

    def test_grt_3000_scores_4(self):
        v = _make_vessel(mmsi="100000002", grt=3000)
        self.assertEqual(_score_vessel_size(v), 4)

    def test_grt_9999_scores_4(self):
        v = _make_vessel(mmsi="100000003", grt=9999)
        self.assertEqual(_score_vessel_size(v), 4)

    def test_grt_10000_scores_8(self):
        v = _make_vessel(mmsi="100000004", grt=10000)
        self.assertEqual(_score_vessel_size(v), 8)

    def test_grt_19999_scores_8(self):
        v = _make_vessel(mmsi="100000005", grt=19999)
        self.assertEqual(_score_vessel_size(v), 8)

    def test_grt_20000_scores_12(self):
        v = _make_vessel(mmsi="100000006", grt=20000)
        self.assertEqual(_score_vessel_size(v), 12)

    def test_grt_49999_scores_12(self):
        v = _make_vessel(mmsi="100000007", grt=49999)
        self.assertEqual(_score_vessel_size(v), 12)

    def test_grt_50000_scores_15(self):
        v = _make_vessel(mmsi="100000008", grt=50000)
        self.assertEqual(_score_vessel_size(v), 15)

    def test_grt_none_scores_0_and_reason_size_unknown(self):
        v = _make_vessel(mmsi="100000009", grt=None)
        self.assertEqual(_score_vessel_size(v), 0)
        opp = _make_opp(v, self.port)
        _, reason = calculate_score_and_reason(opp)
        self.assertIn("size unknown", reason)

    # 2. Origin Flag & Repeat Caller
    def test_origin_flag_true(self):
        v = _make_vessel(mmsi="100000010")
        opp = _make_opp(v, self.port)
        opp.came_from_target_port = "AEFJR"
        pts, reasons = _score_origin_and_repeat(v, opp)
        self.assertEqual(pts, 8)
        self.assertIn("came from Fujairah 8", reasons)

    def test_origin_flag_false(self):
        v = _make_vessel(mmsi="100000011")
        opp = _make_opp(v, self.port)
        opp.came_from_target_port = None
        pts, reasons = _score_origin_and_repeat(v, opp)
        self.assertEqual(pts, 0)
        self.assertEqual(len(reasons), 0)

    def test_repeat_caller_1_earlier_obs_gives_0(self):
        now = timezone.now()
        v = _make_vessel(mmsi="100000012")
        VesselObservation.objects.create(
            vessel=v, latitude=1.0, longitude=103.0, source="test", timestamp=now - timedelta(days=5),
            current_port="Singapore"
        )
        opp = _make_opp(v, self.port)
        pts, reasons = _score_origin_and_repeat(v, opp)
        # Only 1 observation total (it's the latest observation, so 0 earlier)
        self.assertEqual(pts, 0)

    def test_repeat_caller_2_earlier_obs_gives_5(self):
        now = timezone.now()
        v = _make_vessel(mmsi="100000013")
        # 1 current observation + 2 earlier observations in last 90 days = 2 earlier observations
        VesselObservation.objects.create(
            vessel=v, latitude=1.0, longitude=103.0, source="test", timestamp=now - timedelta(days=2),
            current_port="Singapore"
        )
        VesselObservation.objects.create(
            vessel=v, latitude=1.0, longitude=103.0, source="test", timestamp=now - timedelta(days=10),
            current_port="Singapore"
        )
        VesselObservation.objects.create(
            vessel=v, latitude=1.0, longitude=103.0, source="test", timestamp=now - timedelta(days=20),
            current_port="Singapore"
        )
        opp = _make_opp(v, self.port)
        pts, reasons = _score_origin_and_repeat(v, opp)
        self.assertEqual(pts, 5)
        self.assertIn("repeat caller 5", reasons)

    def test_repeat_caller_3_earlier_obs_capped(self):
        now = timezone.now()
        v = _make_vessel(mmsi="100000014")
        # Latest + 3 earlier
        for days_ago in [1, 10, 20, 30]:
            VesselObservation.objects.create(
                vessel=v, latitude=1.0, longitude=103.0, source="test", timestamp=now - timedelta(days=days_ago),
                current_port="Singapore"
            )
        opp = _make_opp(v, self.port)
        opp.came_from_target_port = "AEFJR"
        pts, reasons = _score_origin_and_repeat(v, opp)
        # 8 origin + 5 repeat = 13 (at factor cap)
        self.assertEqual(pts, 13)
        self.assertIn("came from Fujairah 8", reasons)
        self.assertIn("repeat caller 5", reasons)

    def test_repeat_caller_older_than_90_days_ignored(self):
        now = timezone.now()
        v = _make_vessel(mmsi="100000015")
        # 1 latest obs + 2 obs older than 90 days
        VesselObservation.objects.create(
            vessel=v, latitude=1.0, longitude=103.0, source="test", timestamp=now - timedelta(days=1),
            current_port="Singapore"
        )
        VesselObservation.objects.create(
            vessel=v, latitude=1.0, longitude=103.0, source="test", timestamp=now - timedelta(days=95),
            current_port="Singapore"
        )
        VesselObservation.objects.create(
            vessel=v, latitude=1.0, longitude=103.0, source="test", timestamp=now - timedelta(days=120),
            current_port="Singapore"
        )
        opp = _make_opp(v, self.port)
        pts, reasons = _score_origin_and_repeat(v, opp)
        self.assertEqual(pts, 0)

    # 3. Manager Roles
    def _test_manager_role(self, role, expected_pts):
        v = _make_vessel(mmsi=f"1000000{abs(hash(role)) % 90 + 10}")
        c = Company.objects.create(name=f"Co {role}", company_type="manager", priority="high")
        VesselRelationship.objects.create(vessel=v, company=c, role=role, source="test")
        self.assertEqual(_score_priority_manager(v), expected_pts)

    def test_manager_role_technical_manager(self):
        self._test_manager_role(RELATIONSHIP_ROLE_TECHNICAL_MANAGER, 20)

    def test_manager_role_ism_manager(self):
        self._test_manager_role(RELATIONSHIP_ROLE_ISM_MANAGER, 20)

    def test_manager_role_commercial_manager(self):
        self._test_manager_role(RELATIONSHIP_ROLE_COMMERCIAL_MANAGER, 20)

    def test_manager_role_operator(self):
        self._test_manager_role(RELATIONSHIP_ROLE_OPERATOR, 20)

    def test_manager_role_manager(self):
        self._test_manager_role(RELATIONSHIP_ROLE_MANAGER, 20)

    def test_owner_roles_not_manager(self):
        self._test_manager_role(RELATIONSHIP_ROLE_OWNER, 0)
        self._test_manager_role(RELATIONSHIP_ROLE_BENEFICIAL_OWNER, 0)

    def test_no_relationships_gives_0_and_does_not_crash(self):
        v = _make_vessel(mmsi="100000088")
        self.assertEqual(_score_priority_manager(v), 0)

    # 4. Anchorage bound zone creation & score ordering
    def test_anchorage_bound_creation_and_score_ordering(self):
        now = timezone.now()
        v_anch = _make_vessel(mmsi="100000091")
        v_bound = _make_vessel(mmsi="100000092")
        v_inbound = _make_vessel(mmsi="100000093")

        # Ingest anchorage bound lead
        lead_dict = {
            "eta": now + timedelta(hours=10),
            "hours_to_eta": 10.0,
            "is_inbound": True,
            "eta_source": "eta_calc",
        }
        opp_bound, status = apply_lead(v_bound, self.port, lead_dict, port_area=PORT_AREA_ANCHORAGE_BOUND)
        self.assertEqual(status, "created")
        self.assertEqual(opp_bound.zone, ZONE_ANCHORAGE_BOUND)

        opp_anch = _make_opp(v_anch, self.port, zone=ZONE_ANCHORAGE)
        opp_inbound = _make_opp(v_inbound, self.port, zone=ZONE_24H, eta=now + timedelta(hours=10))

        score_anch = calculate_score(opp_anch)
        score_bound = calculate_score(opp_bound)
        score_inbound = calculate_score(opp_inbound)

        # Ordering: anchorage > anchorage bound > inbound
        self.assertGreater(score_anch, score_bound)
        self.assertGreater(score_bound, score_inbound)


class CapAndFloorTests(TestCase):
    def setUp(self):
        self.port = _make_port()

    def test_maximal_score_capped_at_100(self):
        now = timezone.now()
        v = _make_vessel(mmsi="200000001", vessel_type="Bulk Carrier", grt=60000)
        c = Company.objects.create(name="Mega Mgr", priority="high")
        VesselRelationship.objects.create(
            vessel=v, company=c, role=RELATIONSHIP_ROLE_TECHNICAL_MANAGER,
            source="test", verified=True,
        )
        # Prior won opp
        v_won = _make_vessel(mmsi="200000002")
        VesselRelationship.objects.create(vessel=v_won, company=c, role=RELATIONSHIP_ROLE_OWNER, source="test")
        _make_opp(v_won, self.port, stage=STAGE_WON)

        # Target port origin & observations
        for d in [1, 10, 20]:
            VesselObservation.objects.create(
                vessel=v, latitude=1.0, longitude=103.0, source="test", timestamp=now - timedelta(days=d),
                current_port="Fujairah"
            )

        opp = _make_opp(v, self.port, zone=ZONE_ANCHORAGE)
        opp.came_from_target_port = "AEFJR"

        # Anchorage (30) + segment (20) + size (15) + manager (20) + verified (20) + won (30) + origin/repeat (13) = 148
        score = calculate_score(opp)
        self.assertEqual(score, 100)

    def test_negative_clamped_to_zero(self):
        from unittest.mock import patch
        v = _make_vessel(mmsi="200000003", grt=1000)
        opp = _make_opp(v, self.port, zone=ZONE_72H, eta=None)
        # Verify score is never negative
        score = calculate_score(opp)
        self.assertGreaterEqual(score, 0)

        # Force negative sum to verify floor at 0
        with patch("services.scoring_service._score_recent_negative", return_value=-100):
            clamped_score = calculate_score(opp)
            self.assertEqual(clamped_score, 0)


class BandEdgeTests(TestCase):
    def test_band_thresholds(self):
        self.assertEqual(get_band(39), "LOW")
        self.assertEqual(get_band(40), "MEDIUM")
        self.assertEqual(get_band(59), "MEDIUM")
        self.assertEqual(get_band(60), "HIGH")
        self.assertEqual(get_band(79), "HIGH")
        self.assertEqual(get_band(80), "HOT")


class RescoreCommandTests(TestCase):
    def setUp(self):
        self.port = _make_port()
        self.open_vessel = _make_vessel(mmsi="300000001", grt=55000, name="TITAN")
        self.open_opp = _make_opp(self.open_vessel, self.port, zone=ZONE_ANCHORAGE, score=30)

        self.closed_vessel = _make_vessel(mmsi="300000002", grt=55000, name="OLD LOST")
        self.closed_opp = _make_opp(self.closed_vessel, self.port, zone=ZONE_ANCHORAGE, score=30, stage=STAGE_LOST)

    def test_dry_run_writes_nothing(self):
        out = io.StringIO()
        call_command("rescore_opportunities", "--dry-run", stdout=out)
        self.open_opp.refresh_from_db()
        self.assertEqual(self.open_opp.score, 30)

    def test_apply_changes_only_open_leads_and_closed_untouched(self):
        initial_history_count = OpportunityStageChange.objects.count()

        out = io.StringIO()
        call_command("rescore_opportunities", "--apply", stdout=out)

        self.open_opp.refresh_from_db()
        self.closed_opp.refresh_from_db()

        # Open lead was rescored (anchorage 30 + size 15 = 45)
        self.assertEqual(self.open_opp.score, 45)
        self.assertIn("size 15", self.open_opp.lead_reason)

        # Closed lead remains untouched
        self.assertEqual(self.closed_opp.score, 30)
        self.assertEqual(self.closed_opp.stage, STAGE_LOST)

        # Stage history untouched
        self.assertEqual(OpportunityStageChange.objects.count(), initial_history_count)

    def test_idempotent_second_apply_changes_nothing(self):
        out1 = io.StringIO()
        call_command("rescore_opportunities", "--apply", stdout=out1)
        self.open_opp.refresh_from_db()
        score_after_first = self.open_opp.score
        zone_after_first = self.open_opp.zone
        reason_after_first = self.open_opp.lead_reason

        out2 = io.StringIO()
        call_command("rescore_opportunities", "--apply", stdout=out2)
        self.open_opp.refresh_from_db()

        self.assertEqual(self.open_opp.score, score_after_first)
        self.assertEqual(self.open_opp.zone, zone_after_first)
        self.assertEqual(self.open_opp.lead_reason, reason_after_first)


class IngestionDedupTests(TestCase):
    def test_exactly_one_opp_per_vessel_port_including_anchorage_bound(self):
        port = _make_port()
        v = _make_vessel(mmsi="400000001")
        now = timezone.now()

        lead_data = {
            "eta": now + timedelta(hours=12),
            "hours_to_eta": 12.0,
            "is_inbound": True,
            "eta_source": "eta_calc",
        }
        opp1, status1 = apply_lead(v, port, lead_data, port_area=PORT_AREA_ANCHORAGE_BOUND)
        self.assertEqual(status1, "created")

        # Second arrival ping for same vessel + port
        opp2, status2 = apply_lead(v, port, lead_data, port_area=PORT_AREA_ANCHORAGE_BOUND)
        self.assertEqual(status2, "updated")
        self.assertEqual(opp1.pk, opp2.pk)

        # Exactly 1 opportunity exists in database
        self.assertEqual(Opportunity.objects.filter(vessel=v, port=port).count(), 1)


class ZoneFilterConsistencyTests(TestCase):
    def setUp(self):
        self.port = _make_port()
        bd_group, _ = Group.objects.get_or_create(name="BD Manager")
        self.user = User.objects.create_user("bd_test_user", password="testpass")
        self.user.groups.add(bd_group)
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_anchorage_query_includes_both_anchorage_and_anchorage_bound(self):
        v1 = _make_vessel(mmsi="500000001")
        v2 = _make_vessel(mmsi="500000002")
        v3 = _make_vessel(mmsi="500000003")

        opp_anch = _make_opp(v1, self.port, zone=ZONE_ANCHORAGE)
        opp_bound = _make_opp(v2, self.port, zone=ZONE_ANCHORAGE_BOUND)
        opp_24h = _make_opp(v3, self.port, zone=ZONE_24H)

        resp = self.client.get("/api/v1/opportunities/?zone=anchorage")
        self.assertEqual(resp.status_code, 200)
        results = resp.data.get("results", resp.data)
        returned_ids = {item["id"] for item in results}

        self.assertIn(opp_anch.id, returned_ids)
        self.assertIn(opp_bound.id, returned_ids)
        self.assertNotIn(opp_24h.id, returned_ids)

    def test_anchorage_bound_specific_filter(self):
        v1 = _make_vessel(mmsi="500000004")
        v2 = _make_vessel(mmsi="500000005")

        opp_anch = _make_opp(v1, self.port, zone=ZONE_ANCHORAGE)
        opp_bound = _make_opp(v2, self.port, zone=ZONE_ANCHORAGE_BOUND)

        resp = self.client.get("/api/v1/opportunities/?zone=anchorage_bound")
        self.assertEqual(resp.status_code, 200)
        results = resp.data.get("results", resp.data)
        returned_ids = {item["id"] for item in results}

        self.assertNotIn(opp_anch.id, returned_ids)
        self.assertIn(opp_bound.id, returned_ids)
