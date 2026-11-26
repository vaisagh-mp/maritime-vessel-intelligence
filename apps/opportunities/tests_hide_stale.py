"""hide_stale filter on GET /api/v1/opportunities/."""
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.opportunities.models import Opportunity
from apps.ports.models import Port
from apps.vessels.models import Vessel

User = get_user_model()


class HideStaleTests(TestCase):
    def setUp(self):
        u = User.objects.create_user("hs_bd", password="pw-Secret-123")
        u.groups.add(Group.objects.get_or_create(name=settings.ROLE_BD_MANAGER)[0])
        self.c = APIClient()
        self.c.force_authenticate(u)
        self.port = Port.objects.create(
            name="Singapore", un_locode="SGSIN", latitude=1.29, longitude=103.85,
            anchorage_latitude=1.25, anchorage_longitude=103.8, geofence_radius_km=30.0, active=True)
        self.n = 0

    def lead(self, eta, inbound=True, zone="24h"):
        self.n += 1
        v = Vessel.objects.create(imo=str(9200000 + self.n), mmsi=str(410000000 + self.n), name=f"H{self.n}")
        return Opportunity.objects.create(vessel=v, port=self.port, zone=zone, score=60, is_inbound=inbound, eta=eta)

    def ids(self, query):
        return {r["id"] for r in self.c.get("/api/v1/opportunities/" + query).json()["results"]}

    def test_hides_only_long_passed_inbound_leads(self):
        now = timezone.now()
        future = self.lead(now + timedelta(hours=3))
        recent = self.lead(now - timedelta(hours=10))
        stale = self.lead(now - timedelta(days=14))
        anchored = self.lead(now - timedelta(days=14), inbound=False, zone="anchorage")
        no_eta = self.lead(None)
        everything = {future.id, recent.id, stale.id, anchored.id, no_eta.id}
        self.assertEqual(self.ids(""), everything)
        self.assertEqual(self.ids("?hide_stale=true"), everything - {stale.id})
        self.assertEqual(self.ids("?hide_stale=false"), everything)

    def test_upcoming_drops_every_passed_eta(self):
        now = timezone.now()
        future = self.lead(now + timedelta(hours=3))
        recent = self.lead(now - timedelta(hours=10))
        stale = self.lead(now - timedelta(days=14))
        no_eta = self.lead(None)
        self.assertEqual(self.ids("?is_inbound=true&upcoming=true"), {future.id, no_eta.id})
        self.assertEqual(self.ids("?is_inbound=true"), {future.id, recent.id, stale.id, no_eta.id})
