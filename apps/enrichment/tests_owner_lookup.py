from datetime import timedelta
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth.models import Group, User
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.enrichment.models import EnrichmentLog
from apps.ports.models import Port
from apps.vessels.models import Vessel
from services import quota_service

OWN_FETCH = "apps.enrichment.management.commands.enrich_ownership.Command._fetch_batch"
S = dict(KPLER_OWNERSHIP_ENABLED=True, KPLER_OWNERSHIP_MONTHLY_IMO_CAP=480, KPLER_QUOTA_RESET_DAY=1,
         OWNERSHIP_MANUAL_DAILY_RESERVE=4, OWNERSHIP_RECHECK_DAYS=180)
CMD = "apps.enrichment.refresh.call_command"


@override_settings(**S)
class OwnerLookupApiTests(TestCase):
    def setUp(self):
        self.vessel = Vessel.objects.create(imo="9308766", mmsi="500000001", name="MANUAL ONE")
        self.client = APIClient()
        self.bd = self.user("bd", settings.ROLE_BD_MANAGER)
        self.admin = self.user("adm", settings.ROLE_ADMIN)
        self.client.force_authenticate(self.bd)

    def user(self, name, role):
        u = User.objects.create_user(name, f"{name}@x.com", "pw")
        u.groups.add(Group.objects.get_or_create(name=role)[0])
        return u

    def url(self, v=None):
        return f"/api/v1/ingest/vessels/{(v or self.vessel).pk}/lookup-owner/"

    def test_needs_login(self):
        self.client.force_authenticate(None)
        self.assertIn(self.client.post(self.url()).status_code, (401, 403))

    @patch(CMD)
    def test_runs_one_manual_lookup(self, cc):
        resp = self.client.post(self.url(), {}, format="json")
        self.assertEqual(resp.status_code, 200)
        kw = cc.call_args.kwargs
        self.assertEqual((kw["imos"], kw["max_imos"], kw["manual"], kw["live"]), (["9308766"], 1, True, True))

    @override_settings(KPLER_OWNERSHIP_ENABLED=False)
    @patch(CMD)
    def test_off_switch(self, cc):
        self.assertEqual(self.client.post(self.url()).status_code, 409)
        cc.assert_not_called()

    @patch(CMD)
    def test_bad_imo(self, cc):
        self.vessel.imo = "123"
        self.vessel.save()
        self.assertEqual(self.client.post(self.url()).status_code, 400)

    @patch(CMD)
    def test_recent_check_refused_and_only_admin_can_force(self, cc):
        self.vessel.ownership_checked_at = timezone.now() - timedelta(days=10)
        self.vessel.save()
        self.assertEqual(self.client.post(self.url(), {"force": True}, format="json").status_code, 409)
        cc.assert_not_called()
        self.client.force_authenticate(self.admin)
        self.assertEqual(self.client.post(self.url(), {"force": True}, format="json").status_code, 200)

    @patch(CMD)
    def test_old_check_is_allowed(self, cc):
        self.vessel.ownership_checked_at = timezone.now() - timedelta(days=200)
        self.vessel.save()
        self.assertEqual(self.client.post(self.url()).status_code, 200)

    @patch(CMD)
    def test_daily_manual_limit(self, cc):
        EnrichmentLog.objects.create(success=True, credits_spent=4, endpoint_called=quota_service.OWNERSHIP_MANUAL_ENDPOINT)
        resp = self.client.post(self.url())
        self.assertEqual(resp.status_code, 429)
        self.assertIn("manual", resp.data["detail"])
        cc.assert_not_called()

    @override_settings(KPLER_OWNERSHIP_MONTHLY_IMO_CAP=0)
    @patch(CMD)
    def test_monthly_limit(self, cc):
        self.assertEqual(self.client.post(self.url()).status_code, 429)

    @patch(CMD, side_effect=RuntimeError("boom sk-secret"))
    def test_failure_is_a_plain_message(self, cc):
        resp = self.client.post(self.url())
        self.assertEqual(resp.status_code, 502)
        self.assertNotIn("secret", str(resp.data))

    def test_status_shows_allowances(self):
        Port.objects.create(name="SG", un_locode="SGSIN", latitude=1, longitude=1, anchorage_latitude=1,
                            anchorage_longitude=1, geofence_radius_km=5, marinetraffic_port_id=290, active=True)
        data = self.client.get("/api/v1/ingest/status/").data
        self.assertEqual(data["ownership"]["cap"], 480)
        self.assertEqual(data["ownership"]["manual_left_today"], 4)
        self.assertEqual(data["arrivals"][0]["port"], "SGSIN")
        self.assertTrue(data["arrivals"][0]["allowed_now"])

    def test_vessel_api_shows_checked_date(self):
        self.vessel.ownership_checked_at = timezone.now()
        self.vessel.save()
        self.assertTrue(self.client.get(f"/api/v1/vessels/{self.vessel.pk}/").data["ownership_checked_at"])
