from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase

from apps.common.tests.test_ingest_expected_arrivals import make_synthetic_row
from apps.enrichment.models import ArrivalsFetch
from apps.ports.models import Port

FETCH = "apps.common.management.commands.ingest_expected_arrivals.fetch_expected_arrivals"


class ArrivalsHistoryTests(TestCase):
    def setUp(self):
        self.port = Port.objects.create(
            name="Singapore", un_locode="SGSIN", latitude=1.29, longitude=103.85, anchorage_latitude=1.25,
            anchorage_longitude=103.8, geofence_radius_km=30.0, marinetraffic_port_id=290, active=True)

    def run_live(self, *extra):
        call_command("ingest_expected_arrivals", mode="arrivals", live=True, ports=["SGSIN"], pause_seconds=0, *extra)

    @patch(FETCH)
    def test_a_live_fetch_records_the_vessels_it_saved(self, mt):
        mt.return_value = [make_synthetic_row(IMO="9100001", MMSI="211100001"),
                           make_synthetic_row(IMO="9100002", MMSI="211100002")]
        self.run_live()
        fetch = ArrivalsFetch.objects.get()
        self.assertEqual((fetch.port, fetch.vessel_count), (self.port, 2))
        self.assertEqual(sorted(i.vessel.imo for i in fetch.items.all()), ["9100001", "9100002"])
        self.assertTrue(all(i.opportunity_id for i in fetch.items.all()))

    @patch(FETCH)
    def test_two_fetches_make_two_records(self, mt):
        mt.return_value = [make_synthetic_row(IMO="9100001", MMSI="211100001")]
        self.run_live()
        self.run_live()
        self.assertEqual(ArrivalsFetch.objects.count(), 2)

    @patch(FETCH)
    def test_dry_run_and_empty_fetch_record_nothing(self, mt):
        mt.return_value = [make_synthetic_row(IMO="9100001", MMSI="211100001")]
        call_command("ingest_expected_arrivals", mode="arrivals", live=True, ports=["SGSIN"], pause_seconds=0, dry_run=True)
        mt.return_value = []
        self.run_live()
        self.assertEqual(ArrivalsFetch.objects.count(), 0)
