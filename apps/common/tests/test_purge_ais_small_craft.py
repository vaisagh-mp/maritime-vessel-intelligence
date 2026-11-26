from datetime import datetime, timezone
from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from apps.common.constants import SOURCE_KPLER_AIS_LATEST, STAGE_DETECTED
from apps.observations.models import VesselObservation
from apps.opportunities.models import Opportunity, OpportunityNote
from apps.ports.models import Port
from apps.vessels.models import Vessel


class PurgeTests(TestCase):
    def setUp(self):
        self.port = Port.objects.create(name="Singapore", un_locode="SGSIN", latitude=1.29, longitude=103.85, anchorage_latitude=1.25, anchorage_longitude=103.8, geofence_radius_km=30.0, active=True)
        self.n = 0

    def make(self, grt=None, source=SOURCE_KPLER_AIS_LATEST, stage=STAGE_DETECTED):
        self.n += 1
        v = Vessel.objects.create(imo=9000000 + self.n, mmsi=500000000 + self.n, name=f"V{self.n}", grt=grt)
        VesselObservation.objects.create(
            vessel=v, timestamp=datetime.now(timezone.utc), latitude=1.2, longitude=103.8, source=source)
        o = Opportunity.objects.create(vessel=v, port=self.port, zone="anchorage", stage=stage)
        return v, o

    def run_cmd(self, *a):
        out = StringIO()
        call_command("purge_ais_small_craft", *a, stdout=out)
        return out.getvalue()

    def test_dry_run_deletes_nothing(self):
        self.make()
        out = self.run_cmd()
        self.assertIn("Vessels to remove: 1", out)
        self.assertEqual(Vessel.objects.count(), 1)

    def test_apply_removes_vessel_and_lead(self):
        self.make()
        self.run_cmd("--apply")
        self.assertEqual(Vessel.objects.count(), 0)
        self.assertEqual(Opportunity.objects.count(), 0)

    def test_keeps_known_size_other_source_and_worked_leads(self):
        self.make(grt=50000)
        self.make(source="marinetraffic:expected_arrivals")
        self.make(stage="contacted")
        _, o = self.make()
        OpportunityNote.objects.create(opportunity=o, text="called agent")
        out = self.run_cmd("--apply")
        self.assertEqual(Vessel.objects.count(), 4)
        self.assertIn("Vessels to remove: 0", out)
