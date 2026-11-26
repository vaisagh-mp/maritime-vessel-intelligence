"""Provider allowances (quota_service) and the owner lookup priority queue (ownership_queue)."""
from datetime import datetime, timedelta, timezone as tz

from django.test import TestCase, override_settings
from django.utils import timezone

from apps.enrichment.models import EnrichmentLog
from apps.opportunities.models import Opportunity
from apps.ports.models import Port
from apps.vessels.models import Vessel
from services import quota_service as q
from services.ownership_queue import ownership_queue

BASE = dict(
    KPLER_OWNERSHIP_MONTHLY_IMO_CAP=480, KPLER_QUOTA_RESET_DAY=1,
    OWNERSHIP_RECHECK_DAYS=180, OWNERSHIP_MANUAL_DAILY_RESERVE=4, MT_ARRIVALS_MIN_GAP_HOURS=23,
    SCORE_BANDS=[(80, "HOT"), (60, "HIGH"), (40, "MEDIUM"), (0, "LOW")],
)


def when(y, m, d, h=12):
    return datetime(y, m, d, h, tzinfo=tz.utc)


def make_port(code="SGSIN"):
    return Port.objects.create(
        name=code, un_locode=code, latitude=1.0, longitude=103.0,
        anchorage_latitude=1.1, anchorage_longitude=103.1, geofence_radius_km=10.0, active=True)


@override_settings(**BASE)
class PeriodTests(TestCase):
    def test_period_is_the_calendar_month_by_default(self):
        p = q.period_bounds(when(2026, 11, 24))
        self.assertEqual((p["start"].date().isoformat(), p["end"].date().isoformat()), ("2026-11-01", "2026-12-01"))
        self.assertEqual((p["days"], p["day_number"]), (30, 24))

    @override_settings(KPLER_QUOTA_RESET_DAY=13)
    def test_period_can_start_on_the_contract_day(self):
        p = q.period_bounds(when(2026, 11, 24))
        self.assertEqual((p["start"].date().isoformat(), p["end"].date().isoformat()), ("2026-11-13", "2026-12-13"))
        before = q.period_bounds(when(2026, 11, 5))
        self.assertEqual((before["start"].date().isoformat(), before["end"].date().isoformat()), ("2026-10-13", "2026-11-13"))

    def test_year_end_rolls_over(self):
        p = q.period_bounds(when(2026, 12, 31))
        self.assertEqual(p["end"].date().isoformat(), "2027-01-01")


@override_settings(**BASE)
class OwnershipBudgetTests(TestCase):
    def looked_up(self, n, at):
        for i in range(n):
            Vessel.objects.create(imo=str(9500000 + Vessel.objects.count()), mmsi=str(500000000 + Vessel.objects.count()),
                                  name=f"L{i}", ownership_checked_at=at)

    def test_usage_counts_only_this_period(self):
        self.looked_up(3, when(2026, 11, 3))
        self.looked_up(5, when(2026, 10, 20))   # last period
        self.assertEqual(q.ownership_used(when(2026, 11, 24)), 3)
        self.assertEqual(q.ownership_remaining(when(2026, 11, 24)), 477)

    def test_even_pace_gives_sixteen_a_day_and_keeps_four_for_the_button(self):
        now = when(2026, 11, 1)
        self.assertEqual(q.pace_pool_today(now), 16)
        self.assertEqual(q.auto_budget_today(now), 12)
        self.assertEqual(q.manual_left_today(now), 4)

    def test_unused_days_carry_over(self):
        # day 10 of 30 with nothing used: 160 may be used so far
        self.assertEqual(q.pace_pool_today(when(2026, 11, 10)), 160)

    def test_over_use_is_paid_back_from_later_days(self):
        self.looked_up(40, when(2026, 11, 2))
        # day 2: target 32, but 40 already used -> nothing today
        self.assertEqual(q.pace_pool_today(when(2026, 11, 2)), 0)
        self.assertEqual(q.auto_budget_today(when(2026, 11, 2)), 0)
        # day 4: target 64 -> 24 left
        self.assertEqual(q.pace_pool_today(when(2026, 11, 4)), 24)

    def test_never_more_than_what_is_left_in_the_month(self):
        self.looked_up(478, when(2026, 11, 20))
        self.assertEqual(q.pace_pool_today(when(2026, 11, 30)), 2)
        self.assertEqual(q.manual_left_today(when(2026, 11, 30)), 2)

    def test_manual_lookups_use_up_the_button_share_and_shrink_the_sync_share(self):
        now = timezone.now()
        EnrichmentLog.objects.create(success=True, credits_spent=3, endpoint_called=q.OWNERSHIP_MANUAL_ENDPOINT)
        self.assertEqual(q.manual_used_today(now), 3)
        self.assertEqual(q.manual_left_today(now), 1)

    def test_failed_lookups_are_not_counted(self):
        EnrichmentLog.objects.create(success=False, credits_spent=0, endpoint_called=q.OWNERSHIP_MANUAL_ENDPOINT)
        self.assertEqual(q.manual_used_today(timezone.now()), 0)

    @override_settings(KPLER_OWNERSHIP_MONTHLY_IMO_CAP=0)
    def test_zero_cap_means_no_lookups(self):
        self.assertEqual(q.auto_budget_today(when(2026, 11, 10)), 0)

    def test_status_summary(self):
        s = q.ownership_status(when(2026, 11, 1))
        self.assertEqual((s["cap"], s["used"], s["remaining"], s["auto_budget_today"], s["manual_left_today"]), (480, 0, 480, 12, 4))
        self.assertEqual(s["period_end"], "2026-12-01")


@override_settings(**BASE)
class ArrivalsGuardTests(TestCase):
    def setUp(self):
        self.port = make_port()

    def log(self, hours_ago, success=True, port=None):
        row = EnrichmentLog.objects.create(
            port=port or self.port, success=success, endpoint_called=q.ARRIVALS_ENDPOINT)
        EnrichmentLog.objects.filter(pk=row.pk).update(timestamp=timezone.now() - timedelta(hours=hours_ago))

    def test_no_call_yet_means_allowed(self):
        self.assertTrue(q.arrivals_allowed("SGSIN"))
        self.assertIsNone(q.arrivals_next_allowed("SGSIN"))

    def test_a_call_a_few_hours_ago_blocks_the_port(self):
        self.log(3)
        self.assertFalse(q.arrivals_allowed("SGSIN"))
        self.assertGreater(q.arrivals_next_allowed("SGSIN"), timezone.now() + timedelta(hours=19))

    def test_a_daily_run_is_never_blocked_by_yesterdays_call(self):
        self.log(24)          # same time yesterday
        self.assertTrue(q.arrivals_allowed("SGSIN"))
        self.log(23.5, success=True)
        self.assertTrue(q.arrivals_allowed("SGSIN"))

    def test_failed_calls_do_not_block(self):
        self.log(1, success=False)
        self.assertTrue(q.arrivals_allowed("SGSIN"))

    def test_each_port_has_its_own_allowance(self):
        self.log(2)
        fuj = make_port("AEFJR")
        self.assertFalse(q.arrivals_allowed("SGSIN"))
        self.assertTrue(q.arrivals_allowed("AEFJR"))
        self.log(2, port=fuj)
        self.assertFalse(q.arrivals_allowed("AEFJR"))


@override_settings(**BASE)
class OwnershipQueueTests(TestCase):
    def setUp(self):
        self.sg = make_port("SGSIN")
        self.fj = make_port("AEFJR")
        self.n = 0

    def lead(self, zone="24h", score=60, grt=50000, port=None, stage="detected", checked=None,
             inbound=False, eta=None, imo=None):
        self.n += 1
        v = Vessel.objects.create(imo=imo or str(9600000 + self.n), mmsi=str(510000000 + self.n),
                                  name=f"Q{self.n}", grt=grt, ownership_checked_at=checked)
        Opportunity.objects.create(vessel=v, port=port or self.sg, zone=zone, score=score, stage=stage,
                                   is_inbound=inbound, eta=eta)
        return v.imo

    def test_order_is_zone_then_score_then_size(self):
        a_72 = self.lead("72h", 90)
        a_24_low = self.lead("24h", 55)
        a_24_high = self.lead("24h", 70)
        a_anch = self.lead("anchorage", 45)
        a_bound = self.lead("anchorage_bound", 99)
        same_score_big = self.lead("24h", 70, grt=140000)
        self.assertEqual(
            ownership_queue(10),
            [same_score_big, a_24_high, a_24_low, a_72, a_bound, a_anch],
        )

    def test_limit_and_zero_limit(self):
        imos = [self.lead("24h", 50 + i) for i in range(5)]
        self.assertEqual(ownership_queue(2), [imos[4], imos[3]])
        self.assertEqual(ownership_queue(0), [])

    def test_low_closed_and_stale_leads_are_left_out(self):
        self.lead("anchorage", 39)                          # LOW
        self.lead("anchorage", 90, stage="won")             # closed
        self.lead("24h", 90, inbound=True, eta=timezone.now() - timedelta(days=14))   # stale
        ok = self.lead("24h", 50, inbound=True, eta=timezone.now() - timedelta(hours=5))
        self.assertEqual(ownership_queue(10), [ok])

    def test_recently_checked_vessels_wait_until_the_recheck_period_is_over(self):
        now = timezone.now()
        self.lead("24h", 90, checked=now - timedelta(days=10))
        old = self.lead("24h", 80, checked=now - timedelta(days=200))
        new = self.lead("24h", 70)
        self.assertEqual(ownership_queue(10), [old, new])

    def test_one_vessel_appears_once_even_with_two_leads(self):
        imo = self.lead("24h", 80)
        v = Vessel.objects.get(imo=imo)
        Opportunity.objects.create(vessel=v, port=self.fj, zone="anchorage", score=70)
        self.assertEqual(ownership_queue(10), [imo])

    def test_port_filter(self):
        sg = self.lead("24h", 60)
        fj = self.lead("24h", 90, port=self.fj)
        self.assertEqual(ownership_queue(10, "SGSIN"), [sg])
        self.assertEqual(ownership_queue(10, "AEFJR"), [fj])

    def test_bad_imos_are_skipped(self):
        self.lead("24h", 90, imo="12345")
        good = self.lead("24h", 60)
        self.assertEqual(ownership_queue(10), [good])


@override_settings(**BASE, OWNERSHIP_DAILY_MAX_IMOS=32)
class DailyCeilingTests(TestCase):
    def test_catching_up_is_capped_per_day(self):
        # day 25 with nothing used: the pace alone would allow 396, the ceiling keeps it at 32
        self.assertEqual(q.auto_budget_today(when(2026, 11, 25)), 32)

    def test_a_second_run_the_same_day_only_gets_what_is_left_of_the_ceiling(self):
        now = timezone.now()
        for i in range(30):
            Vessel.objects.create(imo=str(9400000 + i), mmsi=str(530000000 + i), name=f"C{i}", ownership_checked_at=now)
        self.assertLessEqual(q.auto_budget_today(now), 2)

    def test_ceiling_is_not_needed_on_a_normal_day(self):
        self.assertEqual(q.auto_budget_today(when(2026, 11, 1)), 12)
