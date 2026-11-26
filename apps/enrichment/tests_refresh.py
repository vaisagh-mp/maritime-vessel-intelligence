"""
Tests for the live "Refresh data (live)" button API.
All provider access is mocked. No network call is possible: the fetch function
is patched and a socket guard fails any real connection attempt.
"""
import socket
from datetime import timedelta
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth.models import Group, User
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.common.tests.test_ingest_expected_arrivals import make_synthetic_row
from apps.enrichment import refresh
from apps.enrichment.models import EnrichmentLog, IngestRun, ProviderCallState
from apps.opportunities.models import Opportunity
from apps.ports.models import Port
from integrations.kpler.exceptions import CallLimitError

FETCH = "apps.common.management.commands.ingest_expected_arrivals.fetch_expected_arrivals"
FAKE_KEY = "SENTINEL_MT_KEY_12345"


def _no_network(*args, **kwargs):
    raise AssertionError("A real network connection was attempted in a test")


@override_settings(
    INGEST_REFRESH_SYNC=True,
    INGEST_REFRESH_ENABLED=True,
    INGEST_REFRESH_COOLDOWN_SECONDS=120,
    MARINETRAFFIC_API_KEY=FAKE_KEY,
)
class RefreshApiTests(TestCase):
    URL = "/api/v1/ingest/refresh/"

    def setUp(self):
        patcher = patch.object(socket.socket, "connect", _no_network)
        patcher.start()
        self.addCleanup(patcher.stop)

        self.sg = Port.objects.create(
            name="Singapore", un_locode="SGSIN", latitude=1.29, longitude=103.85,
            anchorage_latitude=1.25, anchorage_longitude=103.8, geofence_radius_km=30.0,
            marinetraffic_port_id=290, active=True,
        )
        Port.objects.create(
            name="Fujairah", un_locode="AEFJR", latitude=25.12, longitude=56.32,
            anchorage_latitude=25.18, anchorage_longitude=56.36, geofence_radius_km=30.0,
            marinetraffic_port_id=790, active=True,
        )
        admin_group, _ = Group.objects.get_or_create(name=settings.ROLE_ADMIN)
        bd_group, _ = Group.objects.get_or_create(name=settings.ROLE_BD_MANAGER)
        self.bd = User.objects.create_user("bd_user", "bd@example.com", "pw")
        self.bd.groups.add(bd_group)
        self.admin = User.objects.create_user("admin_user", "admin@example.com", "pw")
        self.admin.groups.add(admin_group)
        self.norole = User.objects.create_user("norole", "no@example.com", "pw")

        self.client = APIClient()
        self.client.force_authenticate(self.bd)

    def _rows(self):
        return [make_synthetic_row(IMO="9100001", MMSI="211100001"),
                make_synthetic_row(IMO="9100002", MMSI="211100002")]

    # ---- success path -------------------------------------------------------
    @patch(FETCH)
    def test_success_runs_ingest_and_records_summary(self, mock_fetch):
        mock_fetch.return_value = self._rows()
        resp = self.client.post(self.URL, {"port": "SGSIN"}, format="json")
        self.assertEqual(resp.status_code, 202)
        self.assertEqual(resp.data["status"], "success")
        run = IngestRun.objects.get(pk=resp.data["run_id"])
        self.assertEqual(run.status, "success")
        self.assertEqual(run.requested_by, self.bd)
        self.assertEqual(run.summary["raw_rows"], 2)
        self.assertEqual(run.summary["accepted"], 2)
        self.assertEqual(run.summary["vessels_created"], 2)
        self.assertEqual(run.summary["errors"], 0)
        self.assertIsNotNone(run.finished_at)
        self.assertEqual(mock_fetch.call_count, 1)
        self.assertEqual(mock_fetch.call_args.kwargs.get("mode"), "arrivals")
        self.assertTrue(Opportunity.objects.exists())
        self.assertEqual(EnrichmentLog.objects.filter(success=True).count(), 1)

    @patch(FETCH)
    def test_admin_allowed(self, mock_fetch):
        mock_fetch.return_value = self._rows()
        self.client.force_authenticate(self.admin)
        self.assertEqual(self.client.post(self.URL, {"port": "SGSIN"}, format="json").status_code, 202)

    # ---- cooldown -------------------------------------------------------------
    @patch(FETCH)
    def test_second_click_is_rejected_then_allowed_after_cooldown(self, mock_fetch):
        mock_fetch.return_value = self._rows()
        self.assertEqual(self.client.post(self.URL, {"port": "SGSIN"}, format="json").status_code, 202)

        second = self.client.post(self.URL, {"port": "AEFJR"}, format="json")
        self.assertEqual(second.status_code, 429)
        self.assertEqual(second.data["code"], "cooldown")
        self.assertTrue(1 <= second.data["retry_after_seconds"] <= 120)
        self.assertEqual(second["Retry-After"], str(second.data["retry_after_seconds"]))
        self.assertEqual(mock_fetch.call_count, 1)  # no second provider call

        ProviderCallState.objects.update(last_call_at=timezone.now() - timedelta(seconds=121))
        third = self.client.post(self.URL, {"port": "AEFJR"}, format="json")
        self.assertEqual(third.status_code, 202)
        self.assertEqual(mock_fetch.call_count, 2)

    def test_claim_is_atomic_only_one_wins(self):
        self.assertTrue(refresh.claim_cooldown())
        self.assertFalse(refresh.claim_cooldown())
        self.assertGreaterEqual(refresh.cooldown_remaining(), 1)

    def test_cooldown_remaining_rounds_up_and_clears(self):
        self.assertEqual(refresh.cooldown_remaining(), 0)
        ProviderCallState.objects.create(
            provider="marinetraffic", last_call_at=timezone.now() - timedelta(seconds=100)
        )
        self.assertIn(refresh.cooldown_remaining(), (20, 21))
        ProviderCallState.objects.update(last_call_at=timezone.now() - timedelta(seconds=500))
        self.assertEqual(refresh.cooldown_remaining(), 0)

    # ---- validation -----------------------------------------------------------
    @patch(FETCH)
    def test_invalid_or_missing_port(self, mock_fetch):
        for body in ({}, {"port": ""}, {"port": "XXXXX"}, {"port": None}):
            resp = self.client.post(self.URL, body, format="json")
            self.assertEqual(resp.status_code, 400, body)
            self.assertEqual(resp.data["code"], "invalid_port")
        mock_fetch.assert_not_called()
        self.assertIsNone(ProviderCallState.objects.first())

    @patch(FETCH)
    def test_port_without_marinetraffic_id_rejected_without_cooldown(self, mock_fetch):
        Port.objects.filter(un_locode="AEFJR").update(marinetraffic_port_id=None)
        resp = self.client.post(self.URL, {"port": "AEFJR"}, format="json")
        self.assertEqual(resp.status_code, 400)
        mock_fetch.assert_not_called()
        self.assertEqual(refresh.cooldown_remaining(), 0)

    @patch(FETCH)
    def test_missing_key_does_not_consume_cooldown(self, mock_fetch):
        with self.settings(MARINETRAFFIC_API_KEY=""):
            resp = self.client.post(self.URL, {"port": "SGSIN"}, format="json")
        self.assertEqual(resp.status_code, 503)
        self.assertEqual(resp.data["code"], "not_configured")
        mock_fetch.assert_not_called()
        self.assertFalse(ProviderCallState.objects.filter(last_call_at__isnull=False).exists())
        self.assertFalse(IngestRun.objects.exists())

    @patch(FETCH)
    def test_disabled_setting(self, mock_fetch):
        with self.settings(INGEST_REFRESH_ENABLED=False):
            resp = self.client.post(self.URL, {"port": "SGSIN"}, format="json")
        self.assertEqual(resp.status_code, 503)
        self.assertEqual(resp.data["code"], "disabled")
        mock_fetch.assert_not_called()

    @patch(FETCH)
    def test_already_running_returns_409(self, mock_fetch):
        run = IngestRun.objects.create(port_code="SGSIN", status="running")
        resp = self.client.post(self.URL, {"port": "SGSIN"}, format="json")
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.data["code"], "already_running")
        self.assertEqual(resp.data["run_id"], run.pk)
        mock_fetch.assert_not_called()

    # ---- permissions ----------------------------------------------------------
    @patch(FETCH)
    def test_permissions(self, mock_fetch):
        anon = APIClient()
        self.assertIn(anon.post(self.URL, {"port": "SGSIN"}, format="json").status_code, (401, 403))
        self.assertIn(anon.get("/api/v1/ingest/status/").status_code, (401, 403))

        self.client.force_authenticate(self.norole)
        self.assertEqual(self.client.post(self.URL, {"port": "SGSIN"}, format="json").status_code, 403)
        self.assertEqual(self.client.get("/api/v1/ingest/status/").status_code, 403)
        run = IngestRun.objects.create(port_code="SGSIN", status="success")
        self.assertEqual(self.client.get(f"/api/v1/ingest/runs/{run.pk}/").status_code, 403)
        mock_fetch.assert_not_called()

    def test_get_not_allowed_on_refresh(self):
        self.assertEqual(self.client.get(self.URL).status_code, 405)

    # ---- provider failure -----------------------------------------------------
    @patch(FETCH)
    def test_provider_error_is_sanitized_and_cooldown_stays(self, mock_fetch):
        mock_fetch.side_effect = CallLimitError(
            f"Too many calls https://services.marinetraffic.com/api/expectedarrivals/{FAKE_KEY}"
        )
        resp = self.client.post(self.URL, {"port": "SGSIN"}, format="json")
        self.assertEqual(resp.status_code, 202)
        run = IngestRun.objects.get(pk=resp.data["run_id"])
        self.assertEqual(run.status, "failed")
        self.assertNotIn(FAKE_KEY, run.error)
        self.assertIn("{api_key}", run.error)
        self.assertLessEqual(len(run.error), 300)
        self.assertNotIn("Traceback", run.error)
        self.assertNotIn(FAKE_KEY, str(resp.data))
        self.assertGreaterEqual(refresh.cooldown_remaining(), 1)
        self.assertEqual(EnrichmentLog.objects.filter(success=False).count(), 1)

        status = self.client.get("/api/v1/ingest/status/").json()
        self.assertNotIn(FAKE_KEY, str(status))

    @patch(FETCH)
    def test_unexpected_exception_gives_generic_message(self, mock_fetch):
        mock_fetch.side_effect = RuntimeError(f"boom {FAKE_KEY}")
        with self.assertLogs("vessel_intel", level="ERROR") as logs:
            resp = self.client.post(self.URL, {"port": "SGSIN"}, format="json")
        run = IngestRun.objects.get(pk=resp.data["run_id"])
        self.assertEqual(run.status, "failed")
        self.assertEqual(run.error, "Unexpected error. See the server log.")
        for line in logs.output:
            self.assertNotIn(FAKE_KEY, line)

    # ---- status endpoints -----------------------------------------------------
    def test_stale_running_run_is_failed_on_status(self):
        old = IngestRun.objects.create(port_code="SGSIN", status="running")
        IngestRun.objects.filter(pk=old.pk).update(started_at=timezone.now() - timedelta(minutes=11))
        data = self.client.get("/api/v1/ingest/status/").json()
        self.assertIsNone(data["running"])
        old.refresh_from_db()
        self.assertEqual(old.status, "failed")
        self.assertEqual(data["last_run"]["run_id"], old.pk)

    @patch(FETCH)
    def test_status_shape_and_no_email(self, mock_fetch):
        mock_fetch.return_value = self._rows()
        self.client.post(self.URL, {"port": "SGSIN"}, format="json")
        data = self.client.get("/api/v1/ingest/status/").json()
        self.assertEqual(set(data), {"enabled", "cooldown_seconds", "cooldown_remaining", "running", "last_run", "ownership", "arrivals"})
        self.assertTrue(data["enabled"])
        self.assertEqual(data["cooldown_seconds"], 120)
        self.assertGreater(data["cooldown_remaining"], 0)
        self.assertEqual(data["last_run"]["requested_by"], "bd_user")
        self.assertNotIn("@", str(data))
        self.assertNotIn(FAKE_KEY, str(data))

    def test_run_detail_and_404(self):
        run = IngestRun.objects.create(port_code="SGSIN", status="success", summary={"accepted": 5})
        ok = self.client.get(f"/api/v1/ingest/runs/{run.pk}/")
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(ok.json()["summary"], {"accepted": 5})
        self.assertEqual(self.client.get("/api/v1/ingest/runs/99999/").status_code, 404)


class ParseReportTests(TestCase):
    def test_parse_report(self):
        text = (
            "\n=== Port: Singapore (SGSIN) [Port ID: 290] ===\nRaw rows: 1293\n"
            "Accepted: 1279\nRejected: 14 (stale_position: 14)\n"
            "Excluded by vessel filter: 0\nVessels created: 707\nVessels updated: 572\n"
            "Observations created: 1279\nOpportunities created: 406, updated: 92, skipped: 781\n"
            "Inbound from other port: 39\nCame from target port: 26\nErrors: 0\n"
        )
        s = refresh.parse_report(text)
        self.assertEqual(s["raw_rows"], 1293)
        self.assertEqual(s["accepted"], 1279)
        self.assertEqual(s["rejected"], 14)
        self.assertEqual(s["vessels_created"], 707)
        self.assertEqual(s["vessels_updated"], 572)
        self.assertEqual(s["opportunities_created"], 406)
        self.assertEqual(s["opportunities_updated"], 92)
        self.assertEqual(s["opportunities_skipped"], 781)
        self.assertEqual(s["errors"], 0)

    def test_parse_empty(self):
        self.assertEqual(refresh.parse_report("No eligible ports to process."), {})


class BoardPageTests(TestCase):
    def test_board_has_live_and_reload_buttons(self):
        group, _ = Group.objects.get_or_create(name=settings.ROLE_BD_MANAGER)
        user = User.objects.create_user("bd_page", "p@example.com", "pw")
        user.groups.add(group)
        self.client.force_login(user)
        html = self.client.get("/").content.decode()
        self.assertIn('id="btn-live-refresh"', html)
        self.assertIn("Refresh data (live)", html)
        self.assertIn('id="btn-refresh"', html)
        self.assertIn(">Reload<", html)
        self.assertIn("refresh.js", html)
        self.assertNotIn("MARINETRAFFIC", html)


class CsrfCookieTests(TestCase):
    def test_board_sets_csrf_cookie_for_logged_in_user(self):
        group, _ = Group.objects.get_or_create(name=settings.ROLE_BD_MANAGER)
        user = User.objects.create_user("bd_csrf", "c@example.com", "pw")
        user.groups.add(group)
        self.client.force_login(user)
        resp = self.client.get("/")
        self.assertIn(settings.CSRF_COOKIE_NAME, resp.cookies)


class CookieNameTests(TestCase):
    def test_cookie_names_are_project_specific(self):
        self.assertEqual(settings.SESSION_COOKIE_NAME, "vi_sessionid")
        self.assertEqual(settings.CSRF_COOKIE_NAME, "vi_csrftoken")
        js = open(settings.BASE_DIR / "apps/web/static/web/js/api.js", encoding="utf-8").read()
        self.assertIn('getCookie("vi_csrftoken")', js)


AIS_FETCH = "apps.common.management.commands.ingest_ais_latest.fetch_ais_latest"


def _ais_feature(mmsi):
    from datetime import datetime, timezone as tz
    now = datetime.now(tz.utc)
    return {"type": "Feature", "geometry": {"type": "Point", "coordinates": [103.85, 1.2]},
            "properties": {"vesselUid": mmsi, "mmsi": mmsi, "imo": 9400001, "sog": 0.0, "cog": 1.0, "navStatus": 1,
                           "vesselName": "AIS SYN ONE", "vesselType": "Bulk Carrier", "grt": 40000,
                           "posDt": (now - timedelta(minutes=5)).isoformat().replace("+00:00", "Z")}}


@override_settings(
    INGEST_REFRESH_SYNC=True, INGEST_REFRESH_ENABLED=True, INGEST_REFRESH_AIS_ENABLED=True,
    MARINETRAFFIC_API_KEY=FAKE_KEY, KPLER_API_KEY="SENTINEL_KPLER_KEY_999",
)
class RefreshAisStepTests(TestCase):
    URL = "/api/v1/ingest/refresh/"

    def setUp(self):
        patcher = patch.object(socket.socket, "connect", _no_network)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.port = Port.objects.create(
            name="Singapore", un_locode="SGSIN", latitude=1.29, longitude=103.85, anchorage_latitude=1.25,
            anchorage_longitude=103.8, geofence_radius_km=30.0, marinetraffic_port_id=290, active=True,
            ais_filter="BBOX(position, 103.5, 1.0, 104.2, 1.5)",
        )
        group, _ = Group.objects.get_or_create(name=settings.ROLE_BD_MANAGER)
        user = User.objects.create_user("bd_ais", "a@example.com", "pw")
        user.groups.add(group)
        self.client = APIClient()
        self.client.force_authenticate(user)

    def _post(self):
        resp = self.client.post(self.URL, {"port": "SGSIN"}, format="json")
        self.assertEqual(resp.status_code, 202)
        return IngestRun.objects.get(pk=resp.data["run_id"])

    @patch(AIS_FETCH)
    @patch(FETCH)
    def test_ais_runs_after_arrivals_and_numbers_are_recorded(self, mt, ais):
        mt.return_value = [make_synthetic_row(IMO="9100001", MMSI="211100001")]
        ais.return_value = {"type": "FeatureCollection", "features": [_ais_feature(563100001)]}
        run = self._post()
        self.assertEqual(run.status, "success")
        self.assertEqual(run.summary["accepted"], 1)
        self.assertEqual(run.summary["ais_in_anchorage"], 1)
        self.assertEqual(run.summary["ais_opportunities_created"], 1)
        self.assertEqual(ais.call_count, 1)
        self.assertEqual(ais.call_args[0][0], "BBOX(position, 103.5, 1.0, 104.2, 1.5)")

    @patch(AIS_FETCH)
    @patch(FETCH)
    def test_ais_failure_does_not_fail_the_run_and_is_sanitized(self, mt, ais):
        mt.return_value = [make_synthetic_row(IMO="9100001", MMSI="211100001")]
        ais.side_effect = CallLimitError("Rate limit key=SENTINEL_KPLER_KEY_999")
        run = self._post()
        self.assertEqual(run.status, "success")
        self.assertEqual(run.summary["accepted"], 1)
        self.assertIn("ais_error", run.summary)
        self.assertNotIn("SENTINEL_KPLER_KEY_999", str(run.summary))

    @patch(AIS_FETCH)
    @patch(FETCH)
    def test_no_area_filter_skips_ais_without_a_call(self, mt, ais):
        Port.objects.update(ais_filter="")
        mt.return_value = [make_synthetic_row(IMO="9100001", MMSI="211100001")]
        run = self._post()
        self.assertEqual(run.status, "success")
        self.assertEqual(run.summary["ais_skipped"], "no_area_filter")
        ais.assert_not_called()

    @patch(AIS_FETCH)
    @patch(FETCH)
    def test_ais_can_be_switched_off(self, mt, ais):
        mt.return_value = [make_synthetic_row(IMO="9100001", MMSI="211100001")]
        with self.settings(INGEST_REFRESH_AIS_ENABLED=False):
            run = self._post()
        self.assertNotIn("ais_skipped", run.summary)
        ais.assert_not_called()

    @patch(AIS_FETCH)
    @patch(FETCH)
    def test_ais_not_called_when_arrivals_fail(self, mt, ais):
        mt.side_effect = CallLimitError("limit")
        run = self._post()
        self.assertEqual(run.status, "failed")
        ais.assert_not_called()


class ParseAisReportTests(TestCase):
    def test_parse(self):
        text = (
            "\n=== AIS Latest: Singapore (SGSIN) ===\nAIS features: 220\nAccepted: 210\nRejected: 10 (stale_position: 10)\n"
            "In anchorage: 150\nMoored in port: 40\nMoving in area: 20\nVessels created: 12\nVessels updated: 100\n"
            "Excluded by vessel filter: 0\nNot recorded (new vessel, not at anchor): 5\nObservations created: 112\n"
            "Opportunities created: 12, updated: 90, skipped: 0\nErrors: 0\n"
        )
        s = refresh.parse_ais_report(text)
        self.assertEqual(s["ais_features"], 220)
        self.assertEqual(s["ais_in_anchorage"], 150)
        self.assertEqual(s["ais_moored"], 40)
        self.assertEqual(s["ais_vessels_created"], 12)
        self.assertEqual(s["ais_opportunities_created"], 12)
        self.assertEqual(s["ais_opportunities_updated"], 90)
        self.assertEqual(s["ais_errors"], 0)


OWN_FETCH = "apps.enrichment.management.commands.enrich_ownership.fetch_vessels"


def _fixture_nodes():
    import json
    from pathlib import Path

    path = Path(settings.BASE_DIR) / "integrations" / "kpler" / "tests" / "fixtures" / "kpler_sample_trimmed.json"
    return json.loads(path.read_text(encoding="utf-8"))["data"]["vessels"]["nodes"]


@override_settings(
    INGEST_REFRESH_SYNC=True, INGEST_REFRESH_ENABLED=True, INGEST_REFRESH_AIS_ENABLED=False,
    MARINETRAFFIC_API_KEY=FAKE_KEY, KPLER_API_KEY="SENTINEL_KPLER_KEY_999",
)
class RefreshOwnershipStepTests(TestCase):
    """Third step of the button: owner and manager lookup for this port's top leads."""

    URL = "/api/v1/ingest/refresh/"

    def setUp(self):
        patcher = patch.object(socket.socket, "connect", _no_network)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.port = Port.objects.create(
            name="Singapore", un_locode="SGSIN", latitude=1.29, longitude=103.85, anchorage_latitude=1.25,
            anchorage_longitude=103.8, geofence_radius_km=30.0, marinetraffic_port_id=290, active=True,
        )
        self.other = Port.objects.create(
            name="Fujairah", un_locode="AEFJR", latitude=25.1, longitude=56.3, anchorage_latitude=25.15,
            anchorage_longitude=56.4, geofence_radius_km=30.0, marinetraffic_port_id=790, active=True,
        )
        group, _ = Group.objects.get_or_create(name=settings.ROLE_BD_MANAGER)
        user = User.objects.create_user("bd_own", "o@example.com", "pw")
        user.groups.add(group)
        self.client = APIClient()
        self.client.force_authenticate(user)

    def lead(self, imo, port=None, score=50, stage="detected"):
        from apps.vessels.models import Vessel

        v = Vessel.objects.create(imo=str(imo), mmsi=f"5{imo}", name=f"V{imo}")
        return Opportunity.objects.create(vessel=v, port=port or self.port, zone="24h", score=score, stage=stage)

    def _post(self):
        resp = self.client.post(self.URL, {"port": "SGSIN"}, format="json")
        self.assertEqual(resp.status_code, 202)
        return IngestRun.objects.get(pk=resp.data["run_id"])

    # ----- candidates -----
    def test_candidates_are_this_ports_unchecked_open_leads_best_first(self):
        self.lead(9000001, score=45)
        self.lead(9000007, score=10)                            # LOW: not worth a lookup
        self.lead(9000002, score=90)
        self.lead(9000003, score=50, port=self.other)           # other port
        self.lead(9000004, score=80, stage="won")               # closed
        checked = self.lead(9000005, score=95)
        checked.vessel.ownership_checked_at = timezone.now()
        checked.vessel.save()
        stale = self.lead(9000006, score=60)
        stale.vessel.ownership_checked_at = timezone.now() - timedelta(days=200)
        stale.vessel.save()
        self.assertEqual(refresh.ownership_candidates("SGSIN", 10), ["9000002", "9000006", "9000001"])
        self.assertEqual(refresh.ownership_candidates("SGSIN", 2), ["9000002", "9000006"])

    @patch(OWN_FETCH)
    @patch(FETCH)
    def test_arrivals_are_not_called_twice_in_a_day(self, mt, own):
        from apps.enrichment.models import EnrichmentLog
        from services import quota_service

        mt.return_value = []
        EnrichmentLog.objects.create(port=self.port, success=True, endpoint_called=quota_service.ARRIVALS_ENDPOINT)
        with self.settings(KPLER_OWNERSHIP_ENABLED=False):
            run = self._post()
        self.assertEqual(run.status, "success")
        self.assertTrue(run.summary["arrivals_skipped"])
        self.assertTrue(run.summary["arrivals_next_at"])
        mt.assert_not_called()

    @patch(OWN_FETCH)
    @patch(FETCH)
    def test_skipped_arrivals_still_look_up_owners(self, mt, own):
        from apps.enrichment.models import EnrichmentLog
        from services import quota_service

        EnrichmentLog.objects.create(port=self.port, success=True, endpoint_called=quota_service.ARRIVALS_ENDPOINT)
        own.return_value = []
        self.lead(9308766, score=70)
        with self.settings(KPLER_OWNERSHIP_ENABLED=True):
            run = self._post()
        mt.assert_not_called()
        own.assert_called_once()
        self.assertTrue(run.summary["arrivals_skipped"])

    # ----- switches -----
    @patch(OWN_FETCH)
    @patch(FETCH)
    @override_settings(KPLER_OWNERSHIP_ENABLED=False)
    def test_off_by_default_makes_no_kpler_call(self, mt, own):
        mt.return_value = [make_synthetic_row(IMO="9100001", MMSI="211100001")]
        self.lead(9308766)
        run = self._post()
        self.assertEqual(run.status, "success")
        self.assertEqual(run.summary["own_skipped"], "disabled")
        own.assert_not_called()

    @patch(OWN_FETCH)
    @patch(FETCH)
    def test_refresh_switch_turns_the_step_off_completely(self, mt, own):
        mt.return_value = [make_synthetic_row(IMO="9100001", MMSI="211100001")]
        with self.settings(KPLER_OWNERSHIP_ENABLED=True, INGEST_REFRESH_OWNERSHIP_ENABLED=False):
            run = self._post()
        self.assertNotIn("own_skipped", run.summary)
        own.assert_not_called()

    @patch(OWN_FETCH)
    @patch(FETCH)
    def test_no_candidates_means_no_call(self, mt, own):
        mt.return_value = []
        with self.settings(KPLER_OWNERSHIP_ENABLED=True):
            run = self._post()
        self.assertEqual(run.summary.get("own_skipped"), "no_candidates")
        own.assert_not_called()

    # ----- working path -----
    @patch(OWN_FETCH)
    @patch(FETCH)
    def test_enabled_looks_up_the_ports_leads_and_saves_owners(self, mt, own):
        from apps.relationships.models import VesselRelationship

        mt.return_value = []
        own.side_effect = lambda imos: [
            n for n in _fixture_nodes() if str(n["identifier"]["imo"]) in imos
        ]
        for imo in (9308766, 9146297):
            self.lead(imo)
        with self.settings(KPLER_OWNERSHIP_ENABLED=True):
            run = self._post()
        self.assertEqual(run.status, "success")
        self.assertEqual(own.call_count, 1)
        self.assertEqual(sorted(own.call_args[0][0]), ["9146297", "9308766"])
        self.assertEqual(run.summary["own_requested"], 2)
        self.assertEqual(run.summary["own_vessels_updated"], 2)
        self.assertGreater(run.summary["own_relationships_created"], 0)
        self.assertEqual(run.summary["own_errors"], 0)
        self.assertTrue(VesselRelationship.objects.exists())

    @patch(OWN_FETCH)
    @patch(FETCH)
    def test_per_click_cap_is_respected(self, mt, own):
        mt.return_value = []
        own.return_value = []
        for i in range(5):
            self.lead(9100100 + i, score=50 + i)
        with self.settings(KPLER_OWNERSHIP_ENABLED=True, INGEST_REFRESH_OWNERSHIP_MAX_IMOS=3):
            run = self._post()
        self.assertEqual(run.summary["own_requested"], 3)
        self.assertEqual(len(own.call_args[0][0]), 3)

    @patch(OWN_FETCH)
    @patch(FETCH)
    def test_empty_monthly_budget_stops_the_step(self, mt, own):
        mt.return_value = []
        self.lead(9308766)
        with self.settings(KPLER_OWNERSHIP_ENABLED=True, KPLER_OWNERSHIP_MONTHLY_IMO_CAP=0):
            run = self._post()
        self.assertEqual(run.summary.get("own_skipped"), "budget")
        own.assert_not_called()

    # ----- failures never fail the run -----
    @patch(OWN_FETCH)
    @patch(FETCH)
    def test_access_denied_is_reported_and_run_still_succeeds(self, mt, own):
        from integrations.kpler.exceptions import KplerAccessError

        mt.return_value = [make_synthetic_row(IMO="9100001", MMSI="211100001")]
        own.side_effect = KplerAccessError("Not entitled key=SENTINEL_KPLER_KEY_999")
        self.lead(9308766)
        with self.settings(KPLER_OWNERSHIP_ENABLED=True, KPLER_API_KEY="SENTINEL_KPLER_KEY_999"):
            run = self._post()
        self.assertEqual(run.status, "success")
        self.assertEqual(run.summary["accepted"], 1)
        self.assertIn("own_error", run.summary)
        self.assertNotIn("SENTINEL_KPLER_KEY_999", str(run.summary))

    @patch(FETCH)
    def test_unexpected_crash_is_contained(self, mt):
        from django.core.management import call_command as real_call_command

        mt.return_value = [make_synthetic_row(IMO="9100001", MMSI="211100001")]
        self.lead(9308766)

        def fake_call(name, *args, **kwargs):
            if name == "enrich_ownership":
                raise RuntimeError("boom")
            return real_call_command(name, *args, **kwargs)

        with self.settings(KPLER_OWNERSHIP_ENABLED=True), patch.object(refresh, "call_command", fake_call):
            run = self._post()
        self.assertEqual(run.status, "success")
        self.assertEqual(run.summary["accepted"], 1)
        self.assertIn("own_error", run.summary)

    @patch(OWN_FETCH)
    @patch(AIS_FETCH)
    @patch(FETCH)
    def test_runs_after_ais_and_not_when_arrivals_fail(self, mt, ais, own):
        mt.side_effect = CallLimitError("limit")
        self.lead(9308766)
        with self.settings(KPLER_OWNERSHIP_ENABLED=True):
            run = self._post()
        self.assertEqual(run.status, "failed")
        own.assert_not_called()


class ParseOwnershipReportTests(TestCase):
    def test_reads_the_live_summary(self):
        text = (
            "=== Live Ownership Enrichment Summary ===\n"
            "IMOs requested             : 12\nVessels updated            : 10\n"
            "Companies created          : 7\nRelationships created      : 21\n"
            "Relationships closed       : 0\nLeads rescored             : 9\nErrors                     : 1\n"
        )
        self.assertEqual(
            refresh.parse_ownership_report(text),
            {"own_requested": 12, "own_vessels_updated": 10, "own_companies_created": 7,
             "own_relationships_created": 21, "own_rescored": 9, "own_errors": 1},
        )
        self.assertEqual(refresh.parse_ownership_report("nothing"), {})


class SanitizeColourCodeTests(SimpleTestCase):
    def test_terminal_colour_codes_are_removed(self):
        from apps.enrichment.refresh import sanitize

        self.assertEqual(sanitize("\x1b[31;1mKpler Access Error\x1b[0m"), "Kpler Access Error")
