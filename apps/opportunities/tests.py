from django.contrib.auth.models import Group, User
from django.test import TestCase
from rest_framework.test import APIClient

from apps.ports.models import Port
from apps.vessels.models import Vessel

from .models import Opportunity


class OpportunityStagePatchTests(TestCase):
    def setUp(self):
        # All opportunity endpoints now require authentication + at least BD Manager role.
        bd_group, _ = Group.objects.get_or_create(name="BD Manager")
        self.bd_user = User.objects.create_user("bd_opp_tester", password="testpass")
        self.bd_user.groups.add(bd_group)

        self.vessel = Vessel.objects.create(mmsi="777", name="TEST VESSEL")
        self.port = Port.objects.create(
            name="Fujairah", un_locode="AEFJR", latitude=25.1, longitude=56.3,
            anchorage_latitude=25.15, anchorage_longitude=56.4, geofence_radius_km=45,
        )
        self.opp = Opportunity.objects.create(
            vessel=self.vessel, port=self.port, zone="anchorage", stage="detected"
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.bd_user)

    def test_patch_updates_only_stage(self):
        response = self.client.patch(
            f"/api/v1/opportunities/{self.opp.id}/", {"stage": "contacted"}, format="json"
        )
        self.assertEqual(response.status_code, 200)
        self.opp.refresh_from_db()
        self.assertEqual(self.opp.stage, "contacted")

    def test_put_not_allowed(self):
        # PUT is excluded from http_method_names — DRF returns 405 (Method Not Allowed)
        # before any permission class runs.
        response = self.client.put(
            f"/api/v1/opportunities/{self.opp.id}/", {"stage": "contacted"}, format="json"
        )
        self.assertEqual(response.status_code, 405)
