from django.test import TestCase
from django.db import IntegrityError

from apps.common.constants import (
    RELATIONSHIP_ROLE_BENEFICIAL_OWNER,
    RELATIONSHIP_ROLE_COMMERCIAL_MANAGER,
    RELATIONSHIP_ROLE_REGISTERED_OWNER,
    RELATIONSHIP_ROLE_ISM_MANAGER,
    RELATIONSHIP_ROLE_TECHNICAL_MANAGER,
)
from apps.companies.models import Company
from apps.vessels.models import Vessel

from .models import VesselRelationship


class VesselRelationshipTests(TestCase):
    def setUp(self):
        self.vessel = Vessel.objects.create(mmsi="123", name="TEST VESSEL")
        self.company = Company.objects.create(name="Verital Marine", company_type="manager")

    def test_unverified_by_default(self):
        rel = VesselRelationship.objects.create(
            vessel=self.vessel, company=self.company, role="manager", source="test-source"
        )
        self.assertFalse(rel.verified)

    def test_duplicate_vessel_company_role_rejected(self):
        VesselRelationship.objects.create(
            vessel=self.vessel, company=self.company, role="manager", source="test-source"
        )
        with self.assertRaises(IntegrityError):
            VesselRelationship.objects.create(
                vessel=self.vessel, company=self.company, role="manager", source="test-source"
            )

    def test_is_current_default_is_true(self):
        rel = VesselRelationship.objects.create(
            vessel=self.vessel, company=self.company, role="manager", source="test-source"
        )
        self.assertTrue(rel.is_current)

    def test_new_roles_are_valid_choices(self):
        for role in [
            RELATIONSHIP_ROLE_TECHNICAL_MANAGER,
            RELATIONSHIP_ROLE_ISM_MANAGER,
            RELATIONSHIP_ROLE_BENEFICIAL_OWNER,
    RELATIONSHIP_ROLE_COMMERCIAL_MANAGER,
    RELATIONSHIP_ROLE_REGISTERED_OWNER,
        ]:
            c = Company.objects.create(name=f"Company {role}", company_type="manager")
            rel = VesselRelationship.objects.create(
                vessel=self.vessel, company=c, role=role, source="test-source"
            )
            # full_clean verifies choices validation
            rel.full_clean()
            self.assertEqual(rel.role, role)

    def test_company_detail_and_role_label(self):
        rel = VesselRelationship.objects.create(
            vessel=self.vessel,
            company=self.company,
            role="manager",
            source="test-source",
            is_current=True,
        )
        from .serializers import VesselRelationshipSerializer
        data = VesselRelationshipSerializer(rel).data
        self.assertEqual(data["role_label"], "Manager")
        self.assertIn("company_detail", data)
        cd = data["company_detail"]
        self.assertEqual(cd["id"], self.company.id)
        self.assertEqual(cd["name"], "Verital Marine")
        self.assertEqual(cd["company_type"], "manager")
        for k in ["country", "email", "website", "address"]:
            self.assertIn(k, cd)


class VesselRelationshipApiFilterTests(TestCase):
    def setUp(self):
        from django.contrib.auth.models import Group, User
        from rest_framework.test import APIClient

        admin_group, _ = Group.objects.get_or_create(name="Admin")
        bd_group, _ = Group.objects.get_or_create(name="BD Manager")

        self.admin_user = User.objects.create_user("admin_rel", password="p")
        self.admin_user.groups.add(admin_group)

        self.bd_user = User.objects.create_user("bd_rel", password="p")
        self.bd_user.groups.add(bd_group)

        self.v1 = Vessel.objects.create(mmsi="111", name="VESSEL 1")
        self.v2 = Vessel.objects.create(mmsi="222", name="VESSEL 2")

        self.c1 = Company.objects.create(name="Company A", company_type="owner")
        self.c2 = Company.objects.create(name="Company B", company_type="manager")

        self.r1 = VesselRelationship.objects.create(
            vessel=self.v1, company=self.c1, role="owner", source="src", is_current=True
        )
        self.r2 = VesselRelationship.objects.create(
            vessel=self.v2, company=self.c2, role="manager", source="src", is_current=False
        )

    def test_both_roles_can_read_and_filters_work(self):
        from rest_framework.test import APIClient

        # BD Manager access
        client = APIClient()
        client.force_authenticate(user=self.bd_user)

        res = client.get("/api/v1/relationships/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["count"], 2)

        # Admin access
        client.force_authenticate(user=self.admin_user)
        res_admin = client.get("/api/v1/relationships/")
        self.assertEqual(res_admin.status_code, 200)

        # Filter by vessel
        res_v1 = client.get(f"/api/v1/relationships/?vessel={self.v1.id}")
        self.assertEqual(res_v1.json()["count"], 1)
        self.assertEqual(res_v1.json()["results"][0]["vessel"], self.v1.id)

        # Filter by company
        res_c2 = client.get(f"/api/v1/relationships/?company={self.c2.id}")
        self.assertEqual(res_c2.json()["count"], 1)
        self.assertEqual(res_c2.json()["results"][0]["company"], self.c2.id)

        # Filter by is_current=true / false
        res_cur = client.get("/api/v1/relationships/?is_current=true")
        self.assertEqual(res_cur.json()["count"], 1)
        self.assertEqual(res_cur.json()["results"][0]["id"], self.r1.id)

        res_past = client.get("/api/v1/relationships/?is_current=false")
        self.assertEqual(res_past.json()["count"], 1)
        self.assertEqual(res_past.json()["results"][0]["id"], self.r2.id)

        # Anonymous access denied
        anon = APIClient()
        res_anon = anon.get("/api/v1/relationships/")
        self.assertIn(res_anon.status_code, (401, 403))

