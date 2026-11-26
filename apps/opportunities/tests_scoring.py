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
    RELATIONSHIP_ROLE_REGISTERED_OWNER,
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
from services.opportunity_service import (
    apply_lead,
    classify_zone_by_eta,
    get_or_create_open_opportunity,
    resolve_zone,
)
from services.scoring_service import (
    _score_contacts,
    _score_origin_and_repeat,
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

    # 3. Manager and owner contact quality
    _contact_counter = 0

    def _contacts(self, role, priority="medium", is_current=True, **company_fields):
        """Score a fresh vessel linked to one new company in ``role``."""
        type(self)._contact_counter += 1
        n = type(self)._contact_counter
        v = _make_vessel(mmsi=f"7000{n:05d}")
        c = Company.objects.create(
            name=f"Co {n}", company_type="manager", priority=priority, **company_fields
        )
        VesselRelationship.objects.create(
            vessel=v, company=c, role=role, source="test", is_current=is_current
        )
        return _score_contacts(v)

    ALL_MANAGER_ROLES = [
        RELATIONSHIP_ROLE_TECHNICAL_MANAGER,
        RELATIONSHIP_ROLE_ISM_MANAGER,
        RELATIONSHIP_ROLE_COMMERCIAL_MANAGER,
        RELATIONSHIP_ROLE_OPERATOR,
        RELATIONSHIP_ROLE_MANAGER,
    ]

    def test_every_manager_role_with_website_and_email_scores_20_without_any_priority(self):
        for role in self.ALL_MANAGER_ROLES:
            with self.subTest(role=role):
                pts, reasons = self._contacts(
                    role, priority="low", website="https://m.example.com", email="a@m.example.com"
                )
                self.assertEqual(pts, 20)
                self.assertEqual(reasons, [f"{role.replace('_', ' ')} with contacts 20"])

    def test_manager_with_only_website_or_only_email_scores_12(self):
        pts, _ = self._contacts(RELATIONSHIP_ROLE_TECHNICAL_MANAGER, website="https://m.example.com")
        self.assertEqual(pts, 12)
        pts, reasons = self._contacts(RELATIONSHIP_ROLE_ISM_MANAGER, email="a@m.example.com")
        self.assertEqual(pts, 12)
        self.assertEqual(reasons, ["ism manager with partial contacts 12"])

    def test_manager_name_only_scores_6(self):
        pts, reasons = self._contacts(RELATIONSHIP_ROLE_TECHNICAL_MANAGER)
        self.assertEqual(pts, 6)
        self.assertEqual(reasons, ["technical manager name only 6"])

    def test_owner_with_email_scores_8_and_name_only_4(self):
        for role in (
            RELATIONSHIP_ROLE_REGISTERED_OWNER,
            RELATIONSHIP_ROLE_BENEFICIAL_OWNER,
            RELATIONSHIP_ROLE_OWNER,
        ):
            with self.subTest(role=role):
                pts, _ = self._contacts(role, email="o@example.com")
                self.assertEqual(pts, 8)
                pts, _ = self._contacts(role)
                self.assertEqual(pts, 4)

    def test_owner_website_alone_does_not_count_as_email(self):
        pts, _ = self._contacts(RELATIONSHIP_ROLE_REGISTERED_OWNER, website="https://o.example.com")
        self.assertEqual(pts, 4)

    def test_best_manager_counts_not_the_sum(self):
        v = _make_vessel(mmsi="710000001")
        full = Company.objects.create(
            name="Full", company_type="manager", website="https://f.example.com", email="a@f.example.com"
        )
        bare = Company.objects.create(name="Bare", company_type="manager")
        VesselRelationship.objects.create(
            vessel=v, company=full, role=RELATIONSHIP_ROLE_TECHNICAL_MANAGER, source="test"
        )
        VesselRelationship.objects.create(
            vessel=v, company=bare, role=RELATIONSHIP_ROLE_ISM_MANAGER, source="test"
        )
        pts, reasons = _score_contacts(v)
        self.assertEqual(pts, 20)  # not 26
        self.assertEqual(len(reasons), 1)

    def test_same_company_in_four_manager_roles_counts_once(self):
        v = _make_vessel(mmsi="710000002")
        c = Company.objects.create(
            name="One Co", company_type="manager", website="https://o.example.com", email="a@o.example.com"
        )
        for role in self.ALL_MANAGER_ROLES[:4]:
            VesselRelationship.objects.create(vessel=v, company=c, role=role, source="test")
        pts, _ = _score_contacts(v)
        self.assertEqual(pts, 20)

    def test_manager_plus_owner_adds_both_parts(self):
        v = _make_vessel(mmsi="710000003")
        m = Company.objects.create(
            name="M", company_type="manager", website="https://m.example.com", email="a@m.example.com"
        )
        o = Company.objects.create(name="O", company_type="owner", email="o@example.com")
        VesselRelationship.objects.create(vessel=v, company=m, role=RELATIONSHIP_ROLE_TECHNICAL_MANAGER, source="t")
        VesselRelationship.objects.create(vessel=v, company=o, role=RELATIONSHIP_ROLE_REGISTERED_OWNER, source="t")
        pts, reasons = _score_contacts(v)
        self.assertEqual(pts, 28)  # 20 + 8
        self.assertEqual(len(reasons), 2)

    def test_priority_high_adds_5_and_priority_medium_or_low_adds_nothing(self):
        pts, reasons = self._contacts(RELATIONSHIP_ROLE_TECHNICAL_MANAGER, priority="high")
        self.assertEqual(pts, 6 + 5)
        self.assertIn("high-priority company 5", reasons)
        for priority in ("medium", "low"):
            pts, _ = self._contacts(RELATIONSHIP_ROLE_TECHNICAL_MANAGER, priority=priority)
            self.assertEqual(pts, 6)

    def test_group_cap_is_28(self):
        v = _make_vessel(mmsi="710000004")
        m = Company.objects.create(
            name="M", company_type="manager", priority="high",
            website="https://m.example.com", email="a@m.example.com",
        )
        o = Company.objects.create(name="O", company_type="owner", email="o@example.com")
        VesselRelationship.objects.create(vessel=v, company=m, role=RELATIONSHIP_ROLE_TECHNICAL_MANAGER, source="t")
        VesselRelationship.objects.create(vessel=v, company=o, role=RELATIONSHIP_ROLE_REGISTERED_OWNER, source="t")
        pts, reasons = _score_contacts(v)
        self.assertEqual(pts, 28)  # 20 + 8 + 5 = 33, capped
        self.assertIn("contacts capped at 28", reasons)

    def test_ended_relationship_scores_nothing(self):
        pts, reasons = self._contacts(
            RELATIONSHIP_ROLE_TECHNICAL_MANAGER, is_current=False,
            website="https://m.example.com", email="a@m.example.com",
        )
        self.assertEqual((pts, reasons), (0, []))

    def test_no_relationships_gives_0_and_does_not_crash(self):
        v = _make_vessel(mmsi="100000088")
        self.assertEqual(_score_contacts(v), (0, []))

    def test_unsaved_vessel_gives_0(self):
        self.assertEqual(_score_contacts(Vessel(mmsi="1", name="X")), (0, []))

    def test_contact_reasons_appear_in_the_lead_reason(self):
        v = _make_vessel(mmsi="710000005", grt=60000)
        c = Company.objects.create(
            name="M", company_type="manager", website="https://m.example.com", email="a@m.example.com"
        )
        VesselRelationship.objects.create(vessel=v, company=c, role=RELATIONSHIP_ROLE_TECHNICAL_MANAGER, source="t")
        opp = _make_opp(v, self.port)
        score, reason = calculate_score_and_reason(opp)
        self.assertIn("technical manager with contacts 20", reason)
        self.assertEqual(score, 30 + 15 + 20)  # anchorage + size + manager

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


class EtaPassedZoneTests(TestCase):
    """A passed ETA means "arriving now" (24h zone), never "at anchor"."""

    def setUp(self):
        self.port = _make_port()
        self.now = timezone.now()

    # -- classify_zone_by_eta ------------------------------------------------

    def test_past_eta_is_24h_not_anchorage(self):
        self.assertEqual(classify_zone_by_eta(self.now - timedelta(hours=3), self.now), ZONE_24H)
        self.assertEqual(classify_zone_by_eta(self.now - timedelta(days=5), self.now), ZONE_24H)

    def test_eta_exactly_now_is_24h(self):
        self.assertEqual(classify_zone_by_eta(self.now, self.now), ZONE_24H)

    def test_future_eta_bands_unchanged(self):
        self.assertEqual(classify_zone_by_eta(self.now + timedelta(hours=24), self.now), ZONE_24H)
        self.assertEqual(
            classify_zone_by_eta(self.now + timedelta(hours=24, minutes=1), self.now), ZONE_72H
        )
        self.assertEqual(classify_zone_by_eta(self.now + timedelta(hours=72), self.now), ZONE_72H)
        self.assertEqual(classify_zone_by_eta(self.now + timedelta(hours=200), self.now), ZONE_72H)

    def test_eta_none_keeps_legacy_discovery_behaviour(self):
        self.assertEqual(classify_zone_by_eta(None, self.now), ZONE_ANCHORAGE)

    # -- resolve_zone ----------------------------------------------------------

    def test_resolve_anchorage_observation_wins_over_any_eta(self):
        past = self.now - timedelta(hours=2)
        self.assertEqual(resolve_zone(ZONE_24H, past, "anchorage", self.now), ZONE_ANCHORAGE)
        self.assertEqual(resolve_zone(ZONE_72H, None, "anchorage", self.now), ZONE_ANCHORAGE)

    def test_resolve_passed_eta_with_inbound_observation_is_24h(self):
        past = self.now - timedelta(hours=2)
        self.assertEqual(resolve_zone(ZONE_72H, past, "inbound", self.now), ZONE_24H)

    def test_resolve_passed_eta_without_observation_is_24h(self):
        past = self.now - timedelta(hours=2)
        self.assertEqual(resolve_zone(ZONE_72H, past, None, self.now), ZONE_24H)

    def test_resolve_inbound_observation_corrects_a_wrongly_stored_anchorage(self):
        """A lead stored as anchorage only because its ETA passed goes back to 24h
        when the latest observation says the vessel is still inbound."""
        past = self.now - timedelta(hours=2)
        self.assertEqual(resolve_zone(ZONE_ANCHORAGE, past, "inbound", self.now), ZONE_24H)

    def test_resolve_keeps_anchorage_when_there_is_no_contrary_evidence(self):
        past = self.now - timedelta(hours=2)
        self.assertEqual(resolve_zone(ZONE_ANCHORAGE, past, None, self.now), ZONE_ANCHORAGE)
        self.assertEqual(resolve_zone(ZONE_ANCHORAGE, past, "unknown", self.now), ZONE_ANCHORAGE)
        self.assertEqual(resolve_zone(ZONE_ANCHORAGE, past, "in_port", self.now), ZONE_ANCHORAGE)

    def test_resolve_anchorage_bound_observation(self):
        self.assertEqual(
            resolve_zone(ZONE_72H, self.now + timedelta(hours=10), "anchorage_bound", self.now),
            ZONE_ANCHORAGE_BOUND,
        )
        # already anchorage: stays
        self.assertEqual(
            resolve_zone(ZONE_ANCHORAGE, self.now + timedelta(hours=10), "anchorage_bound", self.now),
            ZONE_ANCHORAGE,
        )

    def test_resolve_no_eta_no_evidence_keeps_the_zone(self):
        self.assertEqual(resolve_zone(ZONE_72H, None, None, self.now), ZONE_72H)
        self.assertEqual(resolve_zone(ZONE_72H, None, "inbound", self.now), ZONE_72H)

    # -- the rescore command ---------------------------------------------------

    def _lead(self, mmsi, name, zone, eta, port_area=None):
        v = _make_vessel(mmsi=mmsi, name=name, grt=45000)
        if port_area is not None:
            VesselObservation.objects.create(
                vessel=v, latitude=1.0, longitude=103.0, source="test",
                timestamp=self.now - timedelta(minutes=30), port_area=port_area,
            )
        return _make_opp(v, self.port, zone=zone, eta=eta, score=40)

    def test_rescore_does_not_move_a_passed_eta_lead_into_anchorage(self):
        """The four leads from the Step 8 dry-run (ELBE POINT and others) jumped to
        anchorage only because their ETA had passed."""
        past = self.now - timedelta(hours=1)
        leads = [
            self._lead(f"72000000{i}", name, ZONE_24H, past, port_area="inbound")
            for i, name in enumerate(["ELBE POINT", "GUAN YUAN FU XING", "FEDERAL INTREPID", "DIONI"])
        ]
        call_command("rescore_opportunities", "--apply", stdout=io.StringIO())
        for opp in leads:
            opp.refresh_from_db()
            self.assertEqual(opp.zone, ZONE_24H, opp.vessel.name)
            # 24h zone 15 + size 12 = 27, not anchorage 30 + 12 = 42
            self.assertEqual(opp.score, 27, opp.vessel.name)

    def test_rescore_moves_to_anchorage_only_with_an_anchorage_observation(self):
        past = self.now - timedelta(hours=1)
        at_anchor = self._lead("720000100", "AT ANCHOR", ZONE_24H, past, port_area="anchorage")
        not_anchor = self._lead("720000101", "NOT ANCHOR", ZONE_24H, past, port_area="inbound")
        call_command("rescore_opportunities", "--apply", stdout=io.StringIO())
        at_anchor.refresh_from_db()
        not_anchor.refresh_from_db()
        self.assertEqual(at_anchor.zone, ZONE_ANCHORAGE)
        self.assertEqual(not_anchor.zone, ZONE_24H)

    def test_rescore_corrects_a_lead_wrongly_stored_as_anchorage(self):
        past = self.now - timedelta(hours=1)
        wrong = self._lead("720000200", "WRONG", ZONE_ANCHORAGE, past, port_area="inbound")
        call_command("rescore_opportunities", "--apply", stdout=io.StringIO())
        wrong.refresh_from_db()
        self.assertEqual(wrong.zone, ZONE_24H)

    def test_rescore_dry_run_reports_zone_changes_but_writes_nothing(self):
        past = self.now - timedelta(hours=1)
        wrong = self._lead("720000300", "WRONG", ZONE_ANCHORAGE, past, port_area="inbound")
        out = io.StringIO()
        call_command("rescore_opportunities", "--dry-run", stdout=out)
        wrong.refresh_from_db()
        self.assertEqual(wrong.zone, ZONE_ANCHORAGE)
        self.assertEqual(wrong.score, 40)
        self.assertIn("No records were modified", out.getvalue())

    def test_rescore_is_idempotent_for_zones(self):
        past = self.now - timedelta(hours=1)
        lead = self._lead("720000400", "X", ZONE_ANCHORAGE, past, port_area="inbound")
        call_command("rescore_opportunities", "--apply", stdout=io.StringIO())
        lead.refresh_from_db()
        first = (lead.zone, lead.score, lead.lead_reason)
        call_command("rescore_opportunities", "--apply", stdout=io.StringIO())
        lead.refresh_from_db()
        self.assertEqual((lead.zone, lead.score, lead.lead_reason), first)
