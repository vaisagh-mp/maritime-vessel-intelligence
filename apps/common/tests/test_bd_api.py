"""Tests for the Business Developer management API (Admin only)."""
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import Client, TestCase
from rest_framework.test import APIClient

from apps.common.constants import STAGE_CONTACTED, STAGE_DETECTED
from apps.opportunities.models import Opportunity, OpportunityNote, OpportunityStageChange
from apps.ports.models import Port
from apps.vessels.models import Vessel

User = get_user_model()
URL = "/api/v1/business-developers/"
GOOD_PW = "Harbour-Light-4821"


class BDApiTests(TestCase):
    def setUp(self):
        self.admin_group, _ = Group.objects.get_or_create(name=settings.ROLE_ADMIN)
        self.bd_group, _ = Group.objects.get_or_create(name=settings.ROLE_BD_MANAGER)
        self.admin = User.objects.create_user("boss", password=GOOD_PW, email="boss@example.com")
        self.admin.groups.add(self.admin_group)
        self.client = APIClient()
        self.client.force_authenticate(self.admin)

    def make_bd(self, username="asha", **kw):
        u = User.objects.create_user(username, password=GOOD_PW, email=f"{username}@example.com", **kw)
        u.groups.add(self.bd_group)
        return u

    def payload(self, **over):
        data = {"first_name": "Ravi", "last_name": "Kumar", "username": "ravi.k",
                "email": "ravi@example.com", "password": GOOD_PW}
        data.update(over)
        return data

    # ----- access -----
    def test_only_admin_can_use_it(self):
        bd = self.make_bd()
        c = APIClient()
        self.assertEqual(c.get(URL).status_code, 401)
        c.force_authenticate(bd)
        self.assertEqual(c.get(URL).status_code, 403)
        self.assertEqual(c.post(URL, self.payload(), format="json").status_code, 403)
        self.assertEqual(c.patch(f"{URL}{bd.pk}/", {"is_active": False}, format="json").status_code, 403)
        self.assertEqual(c.post(f"{URL}{bd.pk}/reset-password/", {"password": GOOD_PW}, format="json").status_code, 403)

    # ----- list -----
    def test_list_shows_only_bd_managers(self):
        self.make_bd("asha")
        User.objects.create_user("plain", password=GOOD_PW)
        both = self.make_bd("both")
        both.groups.add(self.admin_group)
        res = self.client.get(URL).json()
        self.assertEqual([r["username"] for r in res["results"]], ["asha"])
        self.assertEqual(res["count"], 1)

    def test_list_filters_and_activity_counts(self):
        a = self.make_bd("asha", first_name="Asha", last_name="Rao")
        b = self.make_bd("bela", first_name="Bela", last_name="Shah")
        b.is_active = False
        b.save()
        port = Port.objects.create(
            name="Singapore", un_locode="SGSIN", latitude=1.29, longitude=103.85,
            anchorage_latitude=1.25, anchorage_longitude=103.8, geofence_radius_km=30.0, active=True)
        v = Vessel.objects.create(imo="9111111", mmsi="400000001", name="V1")
        opp = Opportunity.objects.create(vessel=v, port=port, zone="24h")
        OpportunityStageChange.objects.create(opportunity=opp, from_stage=STAGE_DETECTED, to_stage=STAGE_CONTACTED, changed_by=a)
        OpportunityNote.objects.create(opportunity=opp, author=a, text="called agent")
        OpportunityNote.objects.create(opportunity=opp, author=a, text="sent quote")
        rows = {r["username"]: r for r in self.client.get(URL).json()["results"]}
        self.assertEqual(rows["asha"]["stage_changes"], 1)
        self.assertEqual(rows["asha"]["notes"], 2)
        self.assertEqual(rows["bela"]["stage_changes"], 0)
        self.assertEqual([r["username"] for r in self.client.get(URL, {"status": "inactive"}).json()["results"]], ["bela"])
        self.assertEqual([r["username"] for r in self.client.get(URL, {"status": "active"}).json()["results"]], ["asha"])
        self.assertEqual([r["username"] for r in self.client.get(URL, {"q": "shah"}).json()["results"]], ["bela"])

    # ----- create -----
    def test_create_makes_a_bd_manager_who_can_sign_in(self):
        res = self.client.post(URL, self.payload(), format="json")
        self.assertEqual(res.status_code, 201, res.content)
        user = User.objects.get(username="ravi.k")
        self.assertTrue(user.groups.filter(name=settings.ROLE_BD_MANAGER).exists())
        self.assertFalse(user.groups.filter(name=settings.ROLE_ADMIN).exists())
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertNotEqual(user.password, GOOD_PW)
        self.assertNotIn("password", res.json())
        self.assertTrue(Client().login(username="ravi.k", password=GOOD_PW))

    def test_create_validation_errors(self):
        res = self.client.post(URL, {}, format="json")
        self.assertEqual(res.status_code, 400)
        for field in ("first_name", "last_name", "username", "email", "password"):
            self.assertIn(field, res.json())

    def test_create_rejects_duplicates_bad_email_and_weak_password(self):
        self.make_bd("asha")
        dup_user = self.client.post(URL, self.payload(username="ASHA"), format="json")
        self.assertIn("username", dup_user.json())
        dup_mail = self.client.post(URL, self.payload(email="ASHA@example.com"), format="json")
        self.assertIn("email", dup_mail.json())
        bad_mail = self.client.post(URL, self.payload(email="not-an-email"), format="json")
        self.assertIn("email", bad_mail.json())
        weak = self.client.post(URL, self.payload(password="12345678"), format="json")
        self.assertIn("password", weak.json())
        short = self.client.post(URL, self.payload(password="Ab1"), format="json")
        self.assertIn("password", short.json())
        self.assertFalse(User.objects.filter(username="ravi.k").exists())

    def test_password_cannot_equal_username(self):
        res = self.client.post(URL, self.payload(username="harbourlight4821", password="harbourlight4821"), format="json")
        self.assertIn("password", res.json())

    # ----- edit / activate -----
    def test_edit_details(self):
        bd = self.make_bd("asha")
        res = self.client.patch(f"{URL}{bd.pk}/", {"first_name": "Asha", "last_name": "Rao", "email": "new@example.com"}, format="json")
        self.assertEqual(res.status_code, 200)
        bd.refresh_from_db()
        self.assertEqual((bd.first_name, bd.last_name, bd.email), ("Asha", "Rao", "new@example.com"))
        self.assertEqual(bd.username, "asha")

    def test_edit_rejects_taken_email_but_allows_own(self):
        a = self.make_bd("asha")
        self.make_bd("bela")
        self.assertIn("email", self.client.patch(f"{URL}{a.pk}/", {"email": "bela@example.com"}, format="json").json())
        self.assertEqual(self.client.patch(f"{URL}{a.pk}/", {"email": "asha@example.com"}, format="json").status_code, 200)

    def test_deactivate_blocks_sign_in_and_reactivate_restores_it(self):
        bd = self.make_bd("asha")
        self.assertEqual(self.client.patch(f"{URL}{bd.pk}/", {"is_active": False}, format="json").status_code, 200)
        self.assertFalse(Client().login(username="asha", password=GOOD_PW))
        self.assertTrue(User.objects.filter(pk=bd.pk).exists())
        self.client.patch(f"{URL}{bd.pk}/", {"is_active": True}, format="json")
        self.assertTrue(Client().login(username="asha", password=GOOD_PW))

    def test_deactivated_user_loses_existing_session(self):
        bd = self.make_bd("asha")
        browser = Client()
        browser.login(username="asha", password=GOOD_PW)
        self.assertEqual(browser.get("/priority/24h/").status_code, 200)
        self.client.patch(f"{URL}{bd.pk}/", {"is_active": False}, format="json")
        self.assertEqual(browser.get("/priority/24h/").status_code, 302)

    def test_admin_cannot_deactivate_self_and_is_not_editable_here(self):
        self_row = self.client.patch(f"{URL}{self.admin.pk}/", {"is_active": False}, format="json")
        self.assertEqual(self_row.status_code, 404)  # admins are not in this list at all
        both = self.make_bd("both")
        both.groups.add(self.admin_group)
        self.assertEqual(self.client.patch(f"{URL}{both.pk}/", {"is_active": False}, format="json").status_code, 404)

    def test_bd_admin_cannot_deactivate_own_account_if_listed(self):
        # An Admin who is only listed because of group membership is excluded, so test the guard directly.
        from apps.common import bd_views

        me = self.make_bd("me_bd")
        me.groups.add(self.admin_group)
        original = bd_views.bd_queryset
        try:
            bd_views.bd_queryset = lambda: User.objects.filter(pk=me.pk)
            c = APIClient()
            c.force_authenticate(me)
            res = c.patch(f"{URL}{me.pk}/", {"is_active": False}, format="json")
            self.assertEqual(res.status_code, 400)
            self.assertIn("is_active", res.json())
        finally:
            bd_views.bd_queryset = original

    def test_is_active_must_be_boolean(self):
        bd = self.make_bd("asha")
        self.assertIn("is_active", self.client.patch(f"{URL}{bd.pk}/", {"is_active": "no"}, format="json").json())

    # ----- reset password -----
    def test_reset_password(self):
        bd = self.make_bd("asha")
        res = self.client.post(f"{URL}{bd.pk}/reset-password/", {"password": "Tidal-Wave-9937"}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertFalse(Client().login(username="asha", password=GOOD_PW))
        self.assertTrue(Client().login(username="asha", password="Tidal-Wave-9937"))

    def test_reset_password_validates_and_404s(self):
        bd = self.make_bd("asha")
        self.assertIn("password", self.client.post(f"{URL}{bd.pk}/reset-password/", {"password": "short"}, format="json").json())
        self.assertIn("password", self.client.post(f"{URL}{bd.pk}/reset-password/", {}, format="json").json())
        self.assertEqual(self.client.post(f"{URL}99999/reset-password/", {"password": GOOD_PW}, format="json").status_code, 404)
        self.assertTrue(Client().login(username="asha", password=GOOD_PW))

    def test_unknown_id_is_404(self):
        self.assertEqual(self.client.patch(f"{URL}99999/", {"is_active": False}, format="json").status_code, 404)
