from django.test import TestCase
from django.utils import timezone

from apps.vessels.models import Vessel

from .models import VesselObservation


class VesselObservationTests(TestCase):
    def setUp(self):
        self.vessel = Vessel.objects.create(mmsi="555", name="TEST VESSEL")

    def test_append_only_two_polls_create_two_rows(self):
        VesselObservation.objects.create(
            vessel=self.vessel, timestamp=timezone.now(), latitude=1.0, longitude=1.0, source="test-source"
        )
        VesselObservation.objects.create(
            vessel=self.vessel, timestamp=timezone.now(), latitude=1.1, longitude=1.1, source="test-source"
        )
        self.assertEqual(VesselObservation.objects.filter(vessel=self.vessel).count(), 2)

    def test_update_is_rejected(self):
        obs = VesselObservation.objects.create(
            vessel=self.vessel, timestamp=timezone.now(), latitude=1.0, longitude=1.0, source="test-source"
        )
        obs.latitude = 2.0
        with self.assertRaises(ValueError):
            obs.save()
