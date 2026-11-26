"""Tests for GET /api/v1/opportunities/summary/ (Dashboard data)."""
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.common.constants import STAGE_CONTACTED, STAGE_DETECTED, STAGE_WON
from apps.enrichment.models import IngestRun
from apps.opportunities.models import Opportunity, OpportunityStageChange
from apps.ports.models import Port
from apps.vessels.models import Vessel

User = get_user_model()
URL = "/api/v1/opportunities/summary/"


def make_port(code, name):
    return Port.objects.create(
        name=name, un_locode=code, latitude=1.29, longitude=103.85,
        anchorage_latitude=1.25, anchorage_longitude=103.8, geofence_radius_km=30.0, active=True,
    )


class SummaryTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user("sum_admin", password="pw-Secret-123")
        self.admin.groups.add(Group.objects.get_or_create(name=settings.ROLE_ADMIN)[0])
        self.bd = User.objects.create_user("sum_bd", password="pw-Secret-123", first_name="Asha", last_name="Rao")
        self.bd.groups.add(Group.objects.get_or_create(name=settings.ROLE_BD_MANAGER)[0])
        self.sg = make_port("SGSIN", "Singapore")
        self.fj = make_port("AEFJR", "Fujairah")
        self.n = 0
        self.client = APIClient()
        self.client.force_authenticate(self.admin)

    def lead(self, port, zone="24h", score=50, stage=STAGE_DETECTED, inbound=False, eta=None):
        self.n += 1
        v = Vessel.objects.create(imo=str(9100000 + self.n), mmsi=str(400000000 + self.n), name=f"V{self.n}")
        return Opportunity.objects.create(
            vessel=v, port=port, zone=zone, score=score, stage=stage, is_inbound=inbound, eta=eta)

    def test_stale_inbound_leads_are_not_counted(self):
        now = timezone.now()
        self.lead(self.sg, "24h", 70, inbound=True, eta=now + timedelta(hours=5))    # real
        self.lead(self.sg, "24h", 70, inbound=True, eta=now - timedelta(hours=10))   # just passed: still counted
        self.lead(self.sg, "24h", 70, inbound=True, eta=now - timedelta(days=14))    # stale
        data = self.client.get(URL).json()
        self.assertEqual(data["totals"]["inbound"], 1)  # only the one whose ETA is still ahead
        self.assertEqual(data["totals"]["zone_24h"], 2)
        self.assertEqual(data["totals"]["open"], 3)

    def test_requires_role(self):
        anon = APIClient()
        self.assertEqual(anon.get(URL).status_code, 401)
        nobody = User.objects.create_user("nobody", password="pw-Secret-123")
        c = APIClient()
        c.force_authenticate(nobody)
        self.assertEqual(c.get(URL).status_code, 403)
        c.force_authenticate(self.bd)
        self.assertEqual(c.get(URL).status_code, 200)

    def test_totals(self):
        self.lead(self.sg, "24h", 90, inbound=True)
        self.lead(self.sg, "72h", 65)
        self.lead(self.fj, "anchorage", 30, stage=STAGE_CONTACTED)
        self.lead(self.fj, "anchorage_bound", 45)
        self.lead(self.fj, "24h", 99, stage=STAGE_WON)  # closed: not in open counts
        t = self.client.get(URL).json()["totals"]
        self.assertEqual(t["open"], 4)
        self.assertEqual(t["hot"], 1)
        self.assertEqual(t["inbound"], 1)
        self.assertEqual(t["zone_24h"], 1)
        self.assertEqual(t["zone_72h"], 1)
        self.assertEqual(t["anchorage"], 2)
        self.assertEqual(t["in_pipeline"], 1)
        self.assertEqual(t["new_24h"], 4)
        self.assertEqual(t["won"], 1)

    def test_port_filter(self):
        self.lead(self.sg, "24h", 90)
        self.lead(self.fj, "24h", 90)
        self.lead(self.fj, "72h", 10)
        data = self.client.get(URL, {"port": self.fj.id}).json()
        self.assertEqual(data["totals"]["open"], 2)
        self.assertEqual(data["totals"]["hot"], 1)

    def test_by_stage_and_by_port(self):
        self.lead(self.sg, stage=STAGE_CONTACTED, score=85)
        self.lead(self.sg)
        data = self.client.get(URL).json()
        stages = {s["stage"]: s["count"] for s in data["by_stage"]}
        self.assertEqual(stages["contacted"], 1)
        self.assertEqual(stages["detected"], 1)
        self.assertNotIn("won", stages)
        ports = {p["un_locode"]: p for p in data["by_port"]}
        self.assertEqual(ports["SGSIN"]["open"], 2)
        self.assertEqual(ports["SGSIN"]["hot"], 1)
        self.assertEqual(ports["AEFJR"]["open"], 0)

    def test_needs_attention_only_old_untouched_high_leads(self):
        old_hot = self.lead(self.sg, score=90)
        old_low = self.lead(self.sg, score=20)
        fresh_hot = self.lead(self.sg, score=95)
        worked = self.lead(self.sg, score=88, stage=STAGE_CONTACTED)
        long_ago = timezone.now() - timedelta(hours=30)
        Opportunity.objects.filter(pk__in=[old_hot.pk, old_low.pk, worked.pk]).update(detected_at=long_ago)
        block = self.client.get(URL).json()["needs_attention"]
        self.assertEqual(block["count"], 1)
        self.assertEqual(block["items"][0]["id"], old_hot.pk)
        self.assertGreaterEqual(block["items"][0]["hours_waiting"], 29)
        self.assertNotIn(fresh_hot.pk, [i["id"] for i in block["items"]])

    def test_recent_activity_names_the_person(self):
        opp = self.lead(self.sg)
        OpportunityStageChange.objects.create(
            opportunity=opp, from_stage=STAGE_DETECTED, to_stage=STAGE_CONTACTED, changed_by=self.bd)
        OpportunityStageChange.objects.create(
            opportunity=opp, from_stage=STAGE_CONTACTED, to_stage=STAGE_WON, changed_by=None)
        rows = self.client.get(URL).json()["recent_activity"]
        self.assertEqual(len(rows), 2)
        by = {r["to_label"]: r["by"] for r in rows}
        self.assertEqual(by["Contacted"], "Asha Rao")
        self.assertEqual(by["Won"], "System")

    def test_last_refresh_per_port(self):
        IngestRun.objects.create(port_code="SGSIN", mode="arrivals", status=IngestRun.STATUS_SUCCESS,
                                 finished_at=timezone.now())
        rows = {r["port"]: r for r in self.client.get(URL).json()["last_refresh"]}
        self.assertEqual(rows["SGSIN"]["status"], "success")
        self.assertIsNone(rows["AEFJR"]["status"])

    def test_empty_database(self):
        data = self.client.get(URL).json()
        self.assertEqual(data["totals"]["open"], 0)
        self.assertEqual(data["needs_attention"]["items"], [])
        self.assertEqual(data["recent_activity"], [])
