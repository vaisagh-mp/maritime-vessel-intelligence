from datetime import timedelta

from django.conf import settings
from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.companies.models import Company
from apps.enrichment.models import EnrichmentLog
from apps.opportunities.models import Opportunity
from apps.ports.models import Port
from apps.relationships.models import VesselRelationship
from apps.vessels.models import Vessel
from apps.enrichment.models import record_arrivals_fetch
from services import quota_service

URL = "/api/v1/opportunities/latest-arrivals/"


class LatestArrivalsTests(TestCase):
    def setUp(self):
        mk = lambda c, i: Port.objects.create(name=c, un_locode=c, latitude=1, longitude=1, anchorage_latitude=1,
                                              anchorage_longitude=1, geofence_radius_km=5, marinetraffic_port_id=i, active=True)
        self.sg, self.fj = mk("SGSIN", 290), mk("AEFJR", 790)
        self.client = APIClient()
        u = User.objects.create_user("bd", "b@x.com", "pw")
        u.groups.add(Group.objects.get_or_create(name=settings.ROLE_BD_MANAGER)[0])
        self.client.force_authenticate(u)
        self.n = 0

    def fetch(self, port, ago_minutes=1):
        row = EnrichmentLog.objects.create(port=port, success=True, endpoint_called=quota_service.ARRIVALS_ENDPOINT)
        at = timezone.now() - timedelta(minutes=ago_minutes)
        EnrichmentLog.objects.filter(pk=row.pk).update(timestamp=at)
        return at

    def lead(self, port, saved_at, score=60):
        self.n += 1
        v = Vessel.objects.create(imo=str(9800000 + self.n), mmsi=str(540000000 + self.n), name=f"L{self.n}")
        o = Opportunity.objects.create(vessel=v, port=port, zone="24h", score=score)
        Opportunity.objects.filter(pk=o.pk).update(updated_at=saved_at)
        return o

    def test_only_leads_saved_by_the_last_fetch_are_listed(self):
        at = self.fetch(self.sg)
        inside = self.lead(self.sg, at + timedelta(minutes=2))
        self.lead(self.sg, at - timedelta(days=2))            # older fetch
        self.lead(self.sg, at + timedelta(hours=3))           # edited long after
        data = self.client.get(URL).data
        self.assertEqual([r["id"] for r in data["results"]], [inside.id])
        fj, sg = data["fetches"]
        self.assertEqual((fj["port"], fj["fetched_at"], fj["vessels"]), ("AEFJR", None, 0))
        self.assertEqual((sg["port"], sg["vessels"], sg["approximate"]), ("SGSIN", 1, True))

    def test_port_filter_by_id_and_code(self):
        a, b = self.fetch(self.sg), self.fetch(self.fj)
        sg = self.lead(self.sg, a + timedelta(minutes=1))
        fj = self.lead(self.fj, b + timedelta(minutes=1))
        self.assertEqual([r["id"] for r in self.client.get(URL, {"port": "AEFJR"}).data["results"]], [fj.id])
        self.assertEqual([r["id"] for r in self.client.get(URL, {"port": str(self.sg.pk)}).data["results"]], [sg.id])

    def test_owner_and_manager_details_and_order(self):
        at = self.fetch(self.sg)
        low = self.lead(self.sg, at + timedelta(minutes=1), score=45)
        top = self.lead(self.sg, at + timedelta(minutes=1), score=85)
        own = Company.objects.create(name="Owner Co", company_type="owner", email="o@own.com", country="Greece")
        mgr = Company.objects.create(name="Mgr Co", company_type="manager", website="https://mgr.com")
        VesselRelationship.objects.create(vessel=top.vessel, company=own, role="registered_owner", verified=True)
        VesselRelationship.objects.create(vessel=top.vessel, company=mgr, role="technical_manager")
        VesselRelationship.objects.create(vessel=top.vessel, company=mgr, role="commercial_manager", is_current=False)
        rows = self.client.get(URL, {"port": "SGSIN"}).data["results"]
        self.assertEqual([r["id"] for r in rows], [top.id, low.id])
        comp = rows[0]["companies"]
        self.assertEqual([(c["group"], c["name"], c["verified"]) for c in comp],
                         [("owner", "Owner Co", True), ("manager", "Mgr Co", False)])
        self.assertEqual(comp[0]["email"], "o@own.com")
        self.assertEqual(rows[1]["companies"], [])

    def test_band_filter_and_paging(self):
        at = self.fetch(self.sg)
        for s in (90, 85, 50):
            self.lead(self.sg, at + timedelta(minutes=1), score=s)
        self.assertEqual(self.client.get(URL, {"band": "HOT"}).data["count"], 2)
        page = self.client.get(URL, {"page_size": 2, "page": 2}).data
        self.assertEqual((page["count"], page["pages"], len(page["results"])), (3, 2, 1))

    def test_needs_a_role(self):
        self.client.force_authenticate(None)
        self.assertIn(self.client.get(URL).status_code, (401, 403))


class FetchHistoryTests(LatestArrivalsTests):
    """The date picker: recorded fetches are exact and survive later saves of the same lead."""

    def record(self, port, pairs, when):
        return record_arrivals_fetch(port, pairs, when=when)

    def test_a_recorded_fetch_is_shown_for_its_day_even_after_the_lead_changed(self):
        yesterday = timezone.now() - timedelta(days=1)
        lead = self.lead(self.sg, timezone.now(), score=70)       # saved again today
        self.record(self.sg, [(lead.vessel, lead)], yesterday)
        day = yesterday.date().isoformat()
        data = self.client.get(URL, {"date": day, "port": "SGSIN"}).data
        self.assertEqual([r["id"] for r in data["results"]], [lead.id])
        self.assertFalse(data["fetches"][0]["approximate"])
        self.assertEqual(data["fetches"][0]["vessels"], 1)
        self.assertIn(day, data["dates"])
        self.assertEqual(self.client.get(URL, {"port": "SGSIN"}).data["results"], [])   # today has no fetch

    def test_counts_for_owner_and_manager_data(self):
        now = timezone.now()
        a, b, c = (self.lead(self.sg, now, score=60 + i) for i in range(3))
        own = Company.objects.create(name="O", company_type="owner")
        mgr = Company.objects.create(name="M", company_type="manager")
        VesselRelationship.objects.create(vessel=a.vessel, company=own, role="registered_owner")
        VesselRelationship.objects.create(vessel=a.vessel, company=mgr, role="technical_manager")
        VesselRelationship.objects.create(vessel=b.vessel, company=mgr, role="commercial_manager")
        self.record(self.sg, [(a.vessel, a), (b.vessel, b), (c.vessel, c)], now)
        f = self.client.get(URL, {"port": "SGSIN"}).data["fetches"][0]
        self.assertEqual((f["vessels"], f["with_owner"], f["with_manager"]), (3, 1, 2))

    def test_bad_date_means_today_and_paging_keeps_counts(self):
        now = timezone.now()
        pairs = [(o.vessel, o) for o in (self.lead(self.sg, now, 50 + i) for i in range(3))]
        self.record(self.sg, pairs, now)
        data = self.client.get(URL, {"date": "nonsense", "port": "SGSIN", "page_size": 2}).data
        self.assertEqual((data["count"], len(data["results"]), data["fetches"][0]["vessels"]), (3, 2, 3))
