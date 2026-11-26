from datetime import datetime, timezone
from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from apps.companies.models import Company
from apps.observations.models import VesselObservation
from apps.opportunities.models import Opportunity
from apps.ports.models import Port
from apps.relationships.models import VesselRelationship
from apps.vessels.models import Vessel


class PurgePlaceholderTests(TestCase):
    def run_cmd(self, *a):
        out = StringIO()
        call_command("purge_placeholder_vessels", *a, stdout=out)
        return out.getvalue()

    def test_dry_run_then_apply(self):
        v = Vessel.objects.create(mmsi="993456789", name="BUOY 1")
        VesselObservation.objects.create(
            vessel=v, timestamp=datetime.now(timezone.utc), latitude=1, longitude=103, source="x")
        real = Vessel.objects.create(mmsi="563000001", name="REAL")
        out = self.run_cmd()
        self.assertIn("Vessels to remove: 1", out)
        self.assertEqual(Vessel.objects.count(), 2)
        self.run_cmd("--apply")
        self.assertEqual(list(Vessel.objects.all()), [real])
        self.assertEqual(VesselObservation.objects.count(), 0)

    def test_protects_vessels_with_lead_or_relationship(self):
        port = Port.objects.create(
            name="Singapore", un_locode="SGSIN", latitude=1.29, longitude=103.85,
            anchorage_latitude=1.25, anchorage_longitude=103.8, geofence_radius_km=30.0, active=True)
        a = Vessel.objects.create(mmsi="999000001", name="A")
        Opportunity.objects.create(vessel=a, port=port, zone="anchorage")
        b = Vessel.objects.create(mmsi="999000002", name="B")
        c = Company.objects.create(name="Owner Co")
        VesselRelationship.objects.create(vessel=b, company=c, role="owner", source="kpler:vessels")
        out = self.run_cmd("--apply")
        self.assertIn("Vessels to remove: 0", out)
        self.assertEqual(Vessel.objects.count(), 2)

    def test_include_untouched_leads_flag(self):
        from apps.common.constants import STAGE_CONTACTED
        port = Port.objects.create(
            name="Singapore", un_locode="SGSIN", latitude=1.29, longitude=103.85,
            anchorage_latitude=1.25, anchorage_longitude=103.8, geofence_radius_km=30.0, active=True)
        a = Vessel.objects.create(mmsi="999000001", name="BUOY")
        Opportunity.objects.create(vessel=a, port=port, zone="anchorage")
        b = Vessel.objects.create(mmsi="999000002", name="WORKED")
        Opportunity.objects.create(vessel=b, port=port, zone="anchorage", stage=STAGE_CONTACTED)
        out = self.run_cmd("--include-untouched-leads")
        self.assertIn("Vessels to remove: 1", out)
        self.assertEqual(Vessel.objects.count(), 2)
        self.run_cmd("--include-untouched-leads", "--apply")
        self.assertEqual([v.name for v in Vessel.objects.all()], ["WORKED"])
