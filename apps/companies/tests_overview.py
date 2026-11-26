"""
apps/companies/tests_overview.py

Tests for the Company Overview and Company Vessels API endpoints.
"""

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.common.constants import CLOSED_STAGES
from apps.companies.models import Company
from apps.opportunities.models import Opportunity
from apps.ports.models import Port
from apps.relationships.models import VesselRelationship
from apps.vessels.models import Vessel

User = get_user_model()


def _make_user(username, role=None):
    """Create a user and optionally assign to a role group."""
    user = User.objects.create_user(username, password="testpass123")
    if role:
        group, _ = Group.objects.get_or_create(name=role)
        user.groups.add(group)
    return user


@override_settings(
    SCORE_BANDS=[(80, "HOT"), (60, "HIGH"), (40, "MEDIUM"), (0, "LOW")],
)
class CompanyOverviewPermissionsTests(TestCase):
    """Permission tests for the overview endpoint: 401 anon, 403 no role, 200 for roles."""

    def setUp(self):
        self.admin = _make_user("admin_co", role=settings.ROLE_ADMIN)
        self.bd = _make_user("bd_co", role=settings.ROLE_BD_MANAGER)
        self.plain = _make_user("plain_co")

    def test_anonymous_gets_401(self):
        client = APIClient()
        r = client.get("/api/v1/companies/overview/")
        self.assertIn(r.status_code, (401, 403))

    def test_no_role_gets_403(self):
        client = APIClient()
        client.force_authenticate(user=self.plain)
        r = client.get("/api/v1/companies/overview/")
        self.assertEqual(r.status_code, 403)

    def test_admin_gets_200(self):
        client = APIClient()
        client.force_authenticate(user=self.admin)
        r = client.get("/api/v1/companies/overview/")
        self.assertEqual(r.status_code, 200)

    def test_bd_gets_200(self):
        client = APIClient()
        client.force_authenticate(user=self.bd)
        r = client.get("/api/v1/companies/overview/")
        self.assertEqual(r.status_code, 200)


@override_settings(
    SCORE_BANDS=[(80, "HOT"), (60, "HIGH"), (40, "MEDIUM"), (0, "LOW")],
)
class CompanyOverviewDataTests(TestCase):
    """Data tests: role counts, vessel dedup, filters, sorting, pagination."""

    def setUp(self):
        self.bd = _make_user("bd_data", role=settings.ROLE_BD_MANAGER)
        self.client = APIClient()
        self.client.force_authenticate(user=self.bd)

        self.port = Port.objects.create(
            name="TestPort", un_locode="TSTP",
            latitude=1.0, longitude=103.0,
            anchorage_latitude=1.1, anchorage_longitude=103.1,
            geofence_radius_km=10.0,
        )

        # Company A: 2 vessels via different roles
        self.company_a = Company.objects.create(
            name="Alpha Corp", company_type="manager", country="Singapore"
        )
        self.vessel_1 = Vessel.objects.create(mmsi="111111111", name="VESSEL ONE")
        self.vessel_2 = Vessel.objects.create(mmsi="222222222", name="VESSEL TWO")
        VesselRelationship.objects.create(
            vessel=self.vessel_1, company=self.company_a, role="manager",
            source="test", is_current=True,
        )
        VesselRelationship.objects.create(
            vessel=self.vessel_2, company=self.company_a, role="owner",
            source="test", is_current=True,
        )

        # Company B: same vessel under two roles → should count as 1 vessel
        self.company_b = Company.objects.create(
            name="Beta Ltd", company_type="owner", country="UAE"
        )
        self.vessel_3 = Vessel.objects.create(mmsi="333333333", name="VESSEL THREE")
        VesselRelationship.objects.create(
            vessel=self.vessel_3, company=self.company_b, role="manager",
            source="test", is_current=True,
        )
        VesselRelationship.objects.create(
            vessel=self.vessel_3, company=self.company_b, role="owner",
            source="test", is_current=True,
        )

        # Non-current relationship → should be ignored
        self.vessel_4 = Vessel.objects.create(mmsi="444444444", name="VESSEL FOUR")
        VesselRelationship.objects.create(
            vessel=self.vessel_4, company=self.company_b, role="operator",
            source="test", is_current=False,
        )

        # Company C: no vessels
        self.company_c = Company.objects.create(
            name="Charlie Inc", company_type="broker", country="Singapore"
        )

        # Open lead on vessel_1
        self.lead_open = Opportunity.objects.create(
            vessel=self.vessel_1, port=self.port, score=85,
            stage="detected", zone="24h", is_inbound=True,
        )
        # Closed lead on vessel_2 → should NOT count as open
        self.lead_closed = Opportunity.objects.create(
            vessel=self.vessel_2, port=self.port, score=70,
            stage="won", zone="24h", is_inbound=False,
        )

    def test_vessel_count_per_role(self):
        """Company A has 2 vessels (one per role)."""
        r = self.client.get("/api/v1/companies/overview/?ordering=name")
        self.assertEqual(r.status_code, 200)
        results = r.data["results"]
        alpha = next(c for c in results if c["name"] == "Alpha Corp")
        self.assertEqual(alpha["vessel_count"], 2)
        self.assertEqual(alpha["role_counts"]["manager"], 1)
        self.assertEqual(alpha["role_counts"]["owner"], 1)

    def test_vessel_under_two_companies(self):
        """A vessel can appear under two companies."""
        # vessel_1 is under company_a. Add it also under company_b.
        VesselRelationship.objects.create(
            vessel=self.vessel_1, company=self.company_b, role="operator",
            source="test", is_current=True,
        )
        r = self.client.get("/api/v1/companies/overview/?ordering=name")
        alpha = next(c for c in r.data["results"] if c["name"] == "Alpha Corp")
        beta = next(c for c in r.data["results"] if c["name"] == "Beta Ltd")
        # vessel_1 should appear under both
        self.assertGreaterEqual(alpha["vessel_count"], 1)
        self.assertGreaterEqual(beta["vessel_count"], 1)

    def test_two_roles_one_vessel_counts_as_one(self):
        """Company B has two roles on vessel_3 → vessel_count should be 1."""
        r = self.client.get("/api/v1/companies/overview/?ordering=name")
        beta = next(c for c in r.data["results"] if c["name"] == "Beta Ltd")
        self.assertEqual(beta["vessel_count"], 1)

    def test_non_current_relationships_ignored(self):
        """Non-current relationships are not counted."""
        r = self.client.get("/api/v1/companies/overview/?ordering=name")
        beta = next(c for c in r.data["results"] if c["name"] == "Beta Ltd")
        # vessel_4 has is_current=False, so it shouldn't be counted
        self.assertEqual(beta["vessel_count"], 1)

    def test_closed_leads_not_counted(self):
        """Closed leads (won, lost) don't count as open."""
        r = self.client.get("/api/v1/companies/overview/?ordering=name")
        alpha = next(c for c in r.data["results"] if c["name"] == "Alpha Corp")
        self.assertEqual(alpha["open_leads"], 1)  # only the detected lead

    def test_filter_by_country(self):
        r = self.client.get("/api/v1/companies/overview/?country=UAE")
        self.assertEqual(r.status_code, 200)
        names = {c["name"] for c in r.data["results"]}
        self.assertIn("Beta Ltd", names)
        self.assertNotIn("Alpha Corp", names)

    def test_filter_by_type(self):
        r = self.client.get("/api/v1/companies/overview/?type=broker")
        names = {c["name"] for c in r.data["results"]}
        self.assertIn("Charlie Inc", names)
        self.assertNotIn("Alpha Corp", names)

    def test_filter_by_role(self):
        r = self.client.get("/api/v1/companies/overview/?role=owner")
        names = {c["name"] for c in r.data["results"]}
        self.assertIn("Beta Ltd", names)
        self.assertNotIn("Charlie Inc", names)

    def test_filter_by_name_q(self):
        r = self.client.get("/api/v1/companies/overview/?q=alpha")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.data["results"]), 1)
        self.assertEqual(r.data["results"][0]["name"], "Alpha Corp")

    def test_filter_has_open_leads(self):
        r = self.client.get("/api/v1/companies/overview/?has_open_leads=true")
        names = {c["name"] for c in r.data["results"]}
        self.assertIn("Alpha Corp", names)
        self.assertNotIn("Charlie Inc", names)

    def test_ordering_by_name(self):
        r = self.client.get("/api/v1/companies/overview/?ordering=name")
        names = [c["name"] for c in r.data["results"]]
        self.assertEqual(names, sorted(names))

    def test_ordering_by_vessels_desc(self):
        r = self.client.get("/api/v1/companies/overview/?ordering=-vessels")
        counts = [c["vessel_count"] for c in r.data["results"]]
        self.assertEqual(counts, sorted(counts, reverse=True))

    def test_ordering_by_vessels_asc(self):
        r = self.client.get("/api/v1/companies/overview/?ordering=vessels")
        counts = [c["vessel_count"] for c in r.data["results"]]
        self.assertEqual(counts, sorted(counts))

    def test_pagination(self):
        r = self.client.get("/api/v1/companies/overview/?page_size=1&page=1")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.data["results"]), 1)
        self.assertGreater(r.data["count"], 1)

    def test_best_band(self):
        """Alpha has a lead with score=85 → should be HOT."""
        r = self.client.get("/api/v1/companies/overview/?ordering=name")
        alpha = next(c for c in r.data["results"] if c["name"] == "Alpha Corp")
        self.assertEqual(alpha["best_band"], "HOT")
        self.assertEqual(alpha["best_score"], 85)

    def test_query_count(self):
        """The overview endpoint shouldn't generate N+1 queries — exactly 7 queries."""
        # Warm up ContentType cache etc.
        self.client.get("/api/v1/companies/overview/")
        with self.assertNumQueries(7):
            self.client.get("/api/v1/companies/overview/")

    def test_role_filter_does_not_shrink_vessel_count(self):
        """Choosing a role keeps the card's total equal to all its vessels."""
        res = self.client.get("/api/v1/companies/overview/?role=owner")
        self.assertEqual(res.status_code, 200)
        by_name = {r["name"]: r for r in res.json()["results"]}
        # Alpha has vessel_1 (manager) and vessel_2 (owner): total stays 2.
        self.assertEqual(by_name["Alpha Corp"]["vessel_count"], 2)
        self.assertEqual(by_name["Alpha Corp"]["role_counts"], {"manager": 1, "owner": 1})
        self.assertNotIn("Charlie Inc", by_name)

    def test_default_page_size_is_12(self):
        for i in range(14):
            Company.objects.create(name=f"Zed {i:02d}", company_type="owner")
        data = self.client.get("/api/v1/companies/overview/").json()
        self.assertEqual(len(data["results"]), 12)
        self.assertEqual(data["count"], 17)  # 3 from setUp + 14

    def test_page_past_the_end_returns_last_page(self):
        res = self.client.get("/api/v1/companies/overview/?page=999&page_size=2")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["count"], 3)
        self.assertEqual(len(data["results"]), 1)  # last page holds the 3rd company



@override_settings(
    SCORE_BANDS=[(80, "HOT"), (60, "HIGH"), (40, "MEDIUM"), (0, "LOW")],
)
class CompanyVesselsTests(TestCase):
    """Tests for the /companies/<id>/vessels/ endpoint."""

    def setUp(self):
        self.bd = _make_user("bd_cv", role=settings.ROLE_BD_MANAGER)
        self.client = APIClient()
        self.client.force_authenticate(user=self.bd)

        self.port = Port.objects.create(
            name="VPort", un_locode="VPRT",
            latitude=1.0, longitude=103.0,
            anchorage_latitude=1.1, anchorage_longitude=103.1,
            geofence_radius_km=10.0,
        )

        self.company = Company.objects.create(
            name="Vessel Owner Co", company_type="owner", country="SG"
        )
        self.v1 = Vessel.objects.create(mmsi="555555555", name="SHIP A", imo="1234567")
        self.v2 = Vessel.objects.create(mmsi="666666666", name="SHIP B")
        VesselRelationship.objects.create(
            vessel=self.v1, company=self.company, role="owner",
            source="test", is_current=True,
        )
        VesselRelationship.objects.create(
            vessel=self.v2, company=self.company, role="manager",
            source="test", is_current=True, verified=True,
        )

        # Open lead on v1
        self.lead = Opportunity.objects.create(
            vessel=self.v1, port=self.port, score=65,
            stage="qualifying", zone="72h", is_inbound=True,
        )

    def test_vessels_listed(self):
        r = self.client.get(f"/api/v1/companies/{self.company.id}/vessels/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["count"], 2)
        names = {v["name"] for v in r.data["results"]}
        self.assertIn("SHIP A", names)
        self.assertIn("SHIP B", names)

    def test_role_filter(self):
        r = self.client.get(f"/api/v1/companies/{self.company.id}/vessels/?role=owner")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["count"], 1)
        self.assertEqual(r.data["results"][0]["name"], "SHIP A")

    def test_open_lead_included(self):
        r = self.client.get(f"/api/v1/companies/{self.company.id}/vessels/")
        ship_a = next(v for v in r.data["results"] if v["name"] == "SHIP A")
        self.assertIsNotNone(ship_a["open_lead"])
        self.assertEqual(ship_a["open_lead"]["id"], self.lead.id)
        self.assertEqual(ship_a["open_lead"]["band"], "HIGH")

    def test_vessel_fields(self):
        r = self.client.get(f"/api/v1/companies/{self.company.id}/vessels/")
        ship_a = next(v for v in r.data["results"] if v["name"] == "SHIP A")
        self.assertEqual(ship_a["imo"], "1234567")
        self.assertIn("owner", ship_a["roles"])

    def test_verified_flag(self):
        r = self.client.get(f"/api/v1/companies/{self.company.id}/vessels/")
        ship_b = next(v for v in r.data["results"] if v["name"] == "SHIP B")
        self.assertTrue(ship_b["verified"])

    def test_permissions_anonymous(self):
        client = APIClient()
        r = client.get(f"/api/v1/companies/{self.company.id}/vessels/")
        self.assertIn(r.status_code, (401, 403))

    def test_permissions_no_role(self):
        plain = _make_user("plain_cv")
        client = APIClient()
        client.force_authenticate(user=plain)
        r = client.get(f"/api/v1/companies/{self.company.id}/vessels/")
        self.assertEqual(r.status_code, 403)

    def test_404_for_nonexistent_company(self):
        r = self.client.get("/api/v1/companies/99999/vessels/")
        self.assertEqual(r.status_code, 404)
