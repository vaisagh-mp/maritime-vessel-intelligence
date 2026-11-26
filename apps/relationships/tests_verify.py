"""Confirming (verifying) an owner/manager link: POST /api/v1/relationships/<id>/verify/ and /unverify/."""
from datetime import date

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from rest_framework.test import APIClient

from apps.companies.models import Company
from apps.opportunities.models import Opportunity
from apps.ports.models import Port
from apps.relationships.models import VesselRelationship
from apps.vessels.models import Vessel

User = get_user_model()


def make_user(name, role=None, **extra):
    u = User.objects.create_user(name, password="pw-Secret-123", **extra)
    if role:
        u.groups.add(Group.objects.get_or_create(name=role)[0])
    return u


class VerifyRelationshipTests(TestCase):
    def setUp(self):
        self.bd = make_user("ver_bd", settings.ROLE_BD_MANAGER, first_name="Asha", last_name="Rao")
        self.admin = make_user("ver_admin", settings.ROLE_ADMIN)
        self.nobody = make_user("ver_nobody")
        self.client = APIClient()
        self.client.force_authenticate(self.bd)
        port = Port.objects.create(
            name="Singapore", un_locode="SGSIN", latitude=1.29, longitude=103.85,
            anchorage_latitude=1.25, anchorage_longitude=103.8, geofence_radius_km=30.0, active=True)
        self.vessel = Vessel.objects.create(imo="9637258", mmsi="441754000", name="HMM VICTORY",
                                            vessel_type="Container Ship", grt=142620)
        self.company = Company.objects.create(
            name="HMM OCEAN SERVICE CO LTD", company_type="manager",
            email="ops@example.com", website="https://example.com")
        self.rel = VesselRelationship.objects.create(
            vessel=self.vessel, company=self.company, role="technical_manager",
            source="kpler:vessels", verified=False, is_current=True)
        self.opp = Opportunity.objects.create(vessel=self.vessel, port=port, zone="24h", score=10)

    def url(self, action, pk=None):
        return f"/api/v1/relationships/{pk or self.rel.id}/{action}/"

    def test_requires_login_and_a_role(self):
        self.assertEqual(APIClient().post(self.url("verify")).status_code, 401)
        c = APIClient()
        c.force_authenticate(self.nobody)
        self.assertEqual(c.post(self.url("verify")).status_code, 403)
        self.assertEqual(c.post(self.url("unverify")).status_code, 403)
        c.force_authenticate(self.admin)
        self.assertEqual(c.post(self.url("verify")).status_code, 200)

    def test_verify_records_who_when_and_how(self):
        res = self.client.post(self.url("verify"), {"note": "  Called the company; confirmed.  "}, format="json")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["verified"])
        self.assertEqual(data["verified_by_name"], "Asha Rao")
        self.assertEqual(data["verification_note"], "Called the company; confirmed.")
        self.assertEqual(data["last_verified_date"], date.today().isoformat())
        self.rel.refresh_from_db()
        self.assertEqual(self.rel.verified_by_id, self.bd.id)

    def test_verify_without_a_note_is_fine(self):
        self.assertEqual(self.client.post(self.url("verify"), {}, format="json").status_code, 200)
        self.rel.refresh_from_db()
        self.assertEqual(self.rel.verification_note, "")

    def test_username_is_used_when_the_user_has_no_full_name(self):
        c = APIClient()
        c.force_authenticate(self.admin)
        self.assertEqual(c.post(self.url("verify")).json()["verified_by_name"], "ver_admin")

    def test_bad_notes_are_rejected(self):
        res = self.client.post(self.url("verify"), {"note": "x" * 301}, format="json")
        self.assertEqual(res.status_code, 400)
        self.assertIn("note", res.json())
        self.assertEqual(self.client.post(self.url("verify"), {"note": 123}, format="json").status_code, 400)
        self.rel.refresh_from_db()
        self.assertFalse(self.rel.verified)

    def test_verifying_adds_the_verified_contact_points_and_unverify_takes_them_back(self):
        from services.opportunity_service import recalculate_score

        recalculate_score(self.opp)  # start from a real, calculated score
        before = Opportunity.objects.get(pk=self.opp.pk).score
        self.client.post(self.url("verify"), {}, format="json")
        after = Opportunity.objects.get(pk=self.opp.pk).score
        self.assertEqual(after - before, 20)
        self.client.post(self.url("unverify"))
        self.assertEqual(Opportunity.objects.get(pk=self.opp.pk).score, before)

    def test_unverify_clears_everything(self):
        self.client.post(self.url("verify"), {"note": "ok"}, format="json")
        res = self.client.post(self.url("unverify"))
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertFalse(data["verified"])
        self.assertEqual(data["verified_by_name"], "")
        self.assertEqual(data["verification_note"], "")
        self.assertIsNone(data["last_verified_date"])

    def test_closed_leads_are_not_rescored(self):
        self.opp.stage = "lost"
        self.opp.save()
        before = Opportunity.objects.get(pk=self.opp.pk).score
        self.client.post(self.url("verify"), {}, format="json")
        self.assertEqual(Opportunity.objects.get(pk=self.opp.pk).score, before)

    def test_a_link_that_is_no_longer_current_cannot_be_changed(self):
        self.rel.is_current = False
        self.rel.save()
        self.assertEqual(self.client.post(self.url("verify")).status_code, 400)
        self.assertEqual(self.client.post(self.url("unverify")).status_code, 400)

    def test_missing_link_is_404_and_get_is_not_allowed(self):
        self.assertEqual(self.client.post(self.url("verify", 99999)).status_code, 404)
        self.assertEqual(self.client.get(self.url("verify")).status_code, 405)

    def test_the_list_still_cannot_be_edited_directly(self):
        res = self.client.patch(f"/api/v1/relationships/{self.rel.id}/", {"verified": True}, format="json")
        self.assertIn(res.status_code, (403, 405))
        self.rel.refresh_from_db()
        self.assertFalse(self.rel.verified)
        self.assertEqual(self.client.get("/api/v1/relationships/?vessel=%d" % self.vessel.id).status_code, 200)
