from django.contrib.auth.models import Group, User
from django.test import TestCase
from rest_framework.test import APIClient

from apps.vessels.models import Vessel
from apps.relationships.models import VesselRelationship

from .models import Company


def _make_bd_client():
    """Return an authenticated APIClient with BD Manager role."""
    bd_group, _ = Group.objects.get_or_create(name="BD Manager")
    user = User.objects.create_user("bd_fleet_tester", password="testpass")
    user.groups.add(bd_group)
    client = APIClient()
    client.force_authenticate(user=user)
    return client


class CompanyModelTests(TestCase):
    def test_str_is_name(self):
        c = Company.objects.create(name="Anglo-Eastern", company_type="manager")
        self.assertEqual(str(c), "Anglo-Eastern")
        self.assertEqual(c.priority, "medium")


class VesselCountDistinctTests(TestCase):
    """Distinct-count correctness: same vessel linked twice (different roles)
    must count as 1, not 2."""

    def setUp(self):
        self.client = _make_bd_client()
        self.company = Company.objects.create(
            name="WAN HAI LINES", company_type="manager", priority="high"
        )
        self.vessel = Vessel.objects.create(mmsi="123456789", name="WAN HAI 501")
        # Link the same vessel twice — once as manager, once as owner
        VesselRelationship.objects.create(
            vessel=self.vessel, company=self.company, role="manager", source="test"
        )
        VesselRelationship.objects.create(
            vessel=self.vessel, company=self.company, role="owner", source="test"
        )

    def test_vessel_count_is_1_not_2(self):
        response = self.client.get(f"/api/v1/companies/{self.company.id}/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["vessel_count"], 1)

    def test_vessel_count_in_list(self):
        response = self.client.get("/api/v1/companies/")
        self.assertEqual(response.status_code, 200)
        results = response.data.get("results", response.data)
        company_data = next(c for c in results if c["id"] == self.company.id)
        self.assertEqual(company_data["vessel_count"], 1)


class VesselCountMultiVesselTests(TestCase):
    """Multi-vessel correctness: one company linked to 3 different vessels."""

    def setUp(self):
        self.client = _make_bd_client()
        self.company = Company.objects.create(
            name="Fleet Corp", company_type="operator", priority="medium"
        )
        for i in range(3):
            v = Vessel.objects.create(mmsi=f"90000000{i}", name=f"FLEET VESSEL {i}")
            VesselRelationship.objects.create(
                vessel=v, company=self.company, role="manager", source="test"
            )

    def test_vessel_count_is_3(self):
        response = self.client.get(f"/api/v1/companies/{self.company.id}/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["vessel_count"], 3)


class VesselCountFilterTests(TestCase):
    """Filter tests for vessel_count_lte and vessel_count_gte query params."""

    def setUp(self):
        self.client = _make_bd_client()

        # Company A: 0 vessels
        self.company_a = Company.objects.create(
            name="No Fleet Co", company_type="broker", priority="low"
        )
        # Company B: 1 vessel
        self.company_b = Company.objects.create(
            name="Small Fleet Co", company_type="manager", priority="medium"
        )
        v1 = Vessel.objects.create(mmsi="800000001", name="SMALL VESSEL 1")
        VesselRelationship.objects.create(
            vessel=v1, company=self.company_b, role="manager", source="test"
        )
        # Company C: 3 vessels
        self.company_c = Company.objects.create(
            name="Big Fleet Co", company_type="operator", priority="high"
        )
        for i in range(3):
            v = Vessel.objects.create(mmsi=f"80000010{i}", name=f"BIG VESSEL {i}")
            VesselRelationship.objects.create(
                vessel=v, company=self.company_c, role="manager", source="test"
            )

    def test_vessel_count_lte_1(self):
        response = self.client.get("/api/v1/companies/?vessel_count_lte=1")
        self.assertEqual(response.status_code, 200)
        results = response.data.get("results", response.data)
        returned_ids = {c["id"] for c in results}
        self.assertIn(self.company_a.id, returned_ids)
        self.assertIn(self.company_b.id, returned_ids)
        self.assertNotIn(self.company_c.id, returned_ids)

    def test_vessel_count_gte_2(self):
        response = self.client.get("/api/v1/companies/?vessel_count_gte=2")
        self.assertEqual(response.status_code, 200)
        results = response.data.get("results", response.data)
        returned_ids = {c["id"] for c in results}
        self.assertNotIn(self.company_a.id, returned_ids)
        self.assertNotIn(self.company_b.id, returned_ids)
        self.assertIn(self.company_c.id, returned_ids)

    def test_vessel_count_exact(self):
        response = self.client.get("/api/v1/companies/?vessel_count=0")
        self.assertEqual(response.status_code, 200)
        results = response.data.get("results", response.data)
        returned_ids = {c["id"] for c in results}
        self.assertIn(self.company_a.id, returned_ids)
        self.assertNotIn(self.company_b.id, returned_ids)
        self.assertNotIn(self.company_c.id, returned_ids)


class VesselCountOrderingTests(TestCase):
    """Ordering test: ?ordering=vessel_count sorts ascending by distinct count."""

    def setUp(self):
        self.client = _make_bd_client()

        self.company_zero = Company.objects.create(
            name="Zero Fleet", company_type="broker"
        )
        self.company_one = Company.objects.create(
            name="One Fleet", company_type="manager"
        )
        v = Vessel.objects.create(mmsi="700000001", name="SOLO VESSEL")
        VesselRelationship.objects.create(
            vessel=v, company=self.company_one, role="manager", source="test"
        )
        self.company_three = Company.objects.create(
            name="Three Fleet", company_type="operator"
        )
        for i in range(3):
            v = Vessel.objects.create(mmsi=f"70000010{i}", name=f"TRIO VESSEL {i}")
            VesselRelationship.objects.create(
                vessel=v, company=self.company_three, role="manager", source="test"
            )

    def test_ordering_ascending(self):
        response = self.client.get("/api/v1/companies/?ordering=vessel_count")
        self.assertEqual(response.status_code, 200)
        results = response.data.get("results", response.data)
        counts = [c["vessel_count"] for c in results]
        self.assertEqual(counts, sorted(counts))

    def test_ordering_descending(self):
        response = self.client.get("/api/v1/companies/?ordering=-vessel_count")
        self.assertEqual(response.status_code, 200)
        results = response.data.get("results", response.data)
        counts = [c["vessel_count"] for c in results]
        self.assertEqual(counts, sorted(counts, reverse=True))


class ExistingFilterRegressionTests(TestCase):
    """Regression: existing company_type and priority filters still work
    after switching from filterset_fields to filterset_class."""

    def setUp(self):
        self.client = _make_bd_client()
        self.manager = Company.objects.create(
            name="Manager Co", company_type="manager", priority="high"
        )
        self.owner = Company.objects.create(
            name="Owner Co", company_type="owner", priority="low"
        )

    def test_filter_by_company_type(self):
        response = self.client.get("/api/v1/companies/?company_type=manager")
        self.assertEqual(response.status_code, 200)
        results = response.data.get("results", response.data)
        returned_ids = {c["id"] for c in results}
        self.assertIn(self.manager.id, returned_ids)
        self.assertNotIn(self.owner.id, returned_ids)

    def test_filter_by_priority(self):
        response = self.client.get("/api/v1/companies/?priority=low")
        self.assertEqual(response.status_code, 200)
        results = response.data.get("results", response.data)
        returned_ids = {c["id"] for c in results}
        self.assertNotIn(self.manager.id, returned_ids)
        self.assertIn(self.owner.id, returned_ids)

    def test_combined_filter(self):
        response = self.client.get(
            "/api/v1/companies/?company_type=manager&priority=high"
        )
        self.assertEqual(response.status_code, 200)
        results = response.data.get("results", response.data)
        returned_ids = {c["id"] for c in results}
        self.assertIn(self.manager.id, returned_ids)
        self.assertNotIn(self.owner.id, returned_ids)
