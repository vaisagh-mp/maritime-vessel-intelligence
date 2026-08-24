from django.test import TestCase

from apps.vessels.models import Vessel

from .models import EnrichmentLog


class EnrichmentLogTests(TestCase):
    def test_logs_failure_and_success(self):
        vessel = Vessel.objects.create(mmsi="999", name="TEST VESSEL")
        EnrichmentLog.objects.create(
            vessel=vessel, endpoint_called="get-vessel-location", success=True, credits_spent=1
        )
        EnrichmentLog.objects.create(
            vessel=vessel, endpoint_called="get-vessel-management-data", success=False,
            credits_spent=0, error_message="timeout",
        )
        self.assertEqual(EnrichmentLog.objects.filter(vessel=vessel).count(), 2)
        self.assertEqual(EnrichmentLog.objects.filter(vessel=vessel, success=False).count(), 1)
