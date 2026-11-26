from datetime import timedelta

from django.conf import settings
from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.opportunities.models import Opportunity
from apps.ports.models import Port
from apps.vessels.models import Vessel

URL = "/api/v1/opportunities/"


class CardFilterTests(TestCase):
    def setUp(self):
        self.port = Port.objects.create(name="SG", un_locode="SGSIN", latitude=1, longitude=1, anchorage_latitude=1,
                                        anchorage_longitude=1, geofence_radius_km=5, marinetraffic_port_id=290, active=True)
        self.client = APIClient()
        u = User.objects.create_user("c", "c@x.com", "pw")
        u.groups.add(Group.objects.get_or_create(name=settings.ROLE_BD_MANAGER)[0])
        self.client.force_authenticate(u)
        self.n = 0

    def lead(self, stage="detected", zone="24h", hours_old=2):
        self.n += 1
        v = Vessel.objects.create(imo=str(9900000 + self.n), mmsi=str(550000000 + self.n), name=f"K{self.n}")
        o = Opportunity.objects.create(vessel=v, port=self.port, zone=zone, stage=stage, score=50)
        Opportunity.objects.filter(pk=o.pk).update(detected_at=timezone.now() - timedelta(hours=hours_old))
        return o.pk

    def ids(self, **params):
        return {r["id"] for r in self.client.get(URL, params).data["results"]}

    def test_pipeline_means_contacted_onward(self):
        a = self.lead("contacted"); b = self.lead("negotiation"); self.lead("detected"); self.lead("won")
        self.assertEqual(self.ids(stage="pipeline", open="true"), {a, b})

    def test_a_normal_stage_still_works(self):
        a = self.lead("quoted"); self.lead("contacted")
        self.assertEqual(self.ids(stage="quoted"), {a})

    def test_new_hours(self):
        fresh = self.lead(hours_old=3); self.lead(hours_old=40)
        self.assertEqual(self.ids(new_hours="24"), {fresh})
        self.assertEqual(len(self.ids(new_hours="abc")), 2)

    def test_all_zones_are_returned_without_a_zone_filter(self):
        ids = {self.lead(zone=z) for z in ("24h", "72h", "anchorage", "anchorage_bound")}
        self.assertEqual(self.ids(open="true"), ids)
