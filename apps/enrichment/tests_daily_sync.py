import socket
from datetime import timedelta
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.enrichment.models import EnrichmentLog
from apps.opportunities.models import Opportunity
from apps.ports.models import Port
from apps.vessels.models import Vessel
from services import quota_service

CMD = "apps.enrichment.management.commands.daily_sync.call_command"
SETTINGS = dict(KPLER_OWNERSHIP_ENABLED=True, INGEST_REFRESH_AIS_ENABLED=False,
                KPLER_OWNERSHIP_MONTHLY_IMO_CAP=480, KPLER_QUOTA_RESET_DAY=1,
                OWNERSHIP_MANUAL_DAILY_RESERVE=4, OWNERSHIP_RECHECK_DAYS=180, MT_ARRIVALS_MIN_GAP_HOURS=23)


def run(*args):
    out, err = StringIO(), StringIO()
    try:
        call_command("daily_sync", *args, "--retry-wait", "0", "--port-pause", "0", stdout=out, stderr=err)
        failed = False
    except CommandError:
        failed = True
    return out.getvalue(), err.getvalue(), failed


@override_settings(**SETTINGS)
class DailySyncTests(TestCase):
    def setUp(self):
        mk = lambda c, i: Port.objects.create(name=c, un_locode=c, latitude=1, longitude=1, anchorage_latitude=1,
                                              anchorage_longitude=1, geofence_radius_km=10, marinetraffic_port_id=i, active=True)
        self.sg, self.fj = mk("SGSIN", 290), mk("AEFJR", 790)
        self.n = 0

    def lead(self, score=70, zone="24h"):
        self.n += 1
        v = Vessel.objects.create(imo=str(9700000 + self.n), mmsi=str(520000000 + self.n), name=f"D{self.n}")
        Opportunity.objects.create(vessel=v, port=self.sg, zone=zone, score=score)
        return v.imo

    def test_dry_run_makes_no_call(self):
        self.lead()
        with patch(CMD) as cc:
            out, err, failed = run("--dry-run")
        cc.assert_not_called()
        self.assertFalse(failed)
        self.assertIn("Would fetch expected arrivals", out)
        self.assertIn("Would look up 1 IMO", out)

    def test_one_arrivals_call_per_port_then_owner_lookup_with_todays_share(self):
        imos = [self.lead(60 + i) for i in range(3)]
        with patch(CMD) as cc:
            out, err, failed = run()
        self.assertFalse(failed)
        names = [(c.args[0], c.kwargs.get("ports")) for c in cc.call_args_list]
        self.assertEqual(names[:2], [("ingest_expected_arrivals", ["AEFJR"]), ("ingest_expected_arrivals", ["SGSIN"])])
        last = cc.call_args_list[-1]
        self.assertEqual(last.args[0], "enrich_ownership")
        self.assertEqual(set(last.kwargs["imos"]), set(imos))

    def test_port_fetched_today_is_skipped(self):
        EnrichmentLog.objects.create(port=self.sg, success=True, endpoint_called=quota_service.ARRIVALS_ENDPOINT)
        with patch(CMD) as cc:
            out, _, _ = run("--skip-ownership")
        self.assertEqual([c.kwargs["ports"] for c in cc.call_args_list], [["AEFJR"]])
        self.assertIn("[SGSIN] Arrivals skipped", out)

    def test_429_is_retried_once(self):
        calls = []

        def fake(name, *a, **k):
            calls.append(name)
            if len(calls) == 1:
                raise CommandError("Provider error: Above service call limit (HTTP 429)")
        with patch(CMD, side_effect=fake):
            out, err, failed = run("--port", "SGSIN", "--skip-ownership")
        self.assertEqual(len(calls), 2)
        self.assertFalse(failed)
        self.assertIn("Retrying once", out)

    def test_second_429_is_a_failure_but_owner_step_still_runs(self):
        self.lead()
        seen = []

        def fake(name, *a, **k):
            seen.append(name)
            if name == "ingest_expected_arrivals":
                raise CommandError("HTTP 429")
        with patch(CMD, side_effect=fake):
            out, err, failed = run("--port", "SGSIN")
        self.assertTrue(failed)
        self.assertEqual(seen, ["ingest_expected_arrivals", "ingest_expected_arrivals", "enrich_ownership"])
        self.assertIn("Arrivals failed", err)

    @override_settings(KPLER_OWNERSHIP_ENABLED=False)
    def test_owner_step_off_when_switched_off(self):
        self.lead()
        with patch(CMD) as cc:
            out, _, _ = run("--skip-arrivals")
        cc.assert_not_called()
        self.assertIn("switched off", out)

    def test_budget_is_todays_share_not_more(self):
        for i in range(30):
            self.lead(50 + i % 40)
        with patch(CMD) as cc:
            run("--skip-arrivals")
        budget = quota_service.auto_budget_today()
        self.assertEqual(len(cc.call_args_list[-1].kwargs["imos"]), min(30, budget))

    def test_nothing_to_look_up(self):
        with patch(CMD) as cc:
            out, _, _ = run("--skip-arrivals")
        cc.assert_not_called()
        self.assertIn("no vessel needs a lookup", out)
