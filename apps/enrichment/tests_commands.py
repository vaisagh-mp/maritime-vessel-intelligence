"""Unit tests for enrich_ownership management command."""
import io
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.opportunities.models import Opportunity
from apps.ports.models import Port
from apps.relationships.models import VesselRelationship
from apps.vessels.models import Vessel
from integrations.kpler.exceptions import KplerAccessError, ProviderRequestError


def _make_port():
    return Port.objects.create(
        name="Singapore",
        un_locode="SGSIN",
        latitude=1.29,
        longitude=103.85,
        anchorage_latitude=1.30,
        anchorage_longitude=103.90,
        geofence_radius_km=40,
    )


class EnrichOwnershipCommandTests(TestCase):
    def setUp(self):
        self.port = _make_port()
        self.fixture_path = (
            Path(__file__).resolve().parent.parent.parent
            / "integrations"
            / "kpler"
            / "tests"
            / "fixtures"
            / "kpler_sample.json"
        )

    @override_settings(KPLER_OWNERSHIP_ENABLED=True)
    @patch("apps.enrichment.management.commands.enrich_ownership.fetch_vessels")
    def test_dry_run_sends_nothing(self, mock_fetch):
        """--live without --apply is a dry-run: prints candidates but never calls API."""
        v = Vessel.objects.create(mmsi="100000001", imo="9146297", name="CANDIDATE")
        Opportunity.objects.create(vessel=v, port=self.port, zone="anchorage", score=50, stage="detected")

        out = io.StringIO()
        call_command("enrich_ownership", "--live", "--dry-run", stdout=out)

        mock_fetch.assert_not_called()
        self.assertIn("[DRY-RUN]", out.getvalue())
        self.assertIn("9146297", out.getvalue())

    @override_settings(KPLER_OWNERSHIP_ENABLED=False)
    @patch("apps.enrichment.management.commands.enrich_ownership.fetch_vessels")
    def test_live_without_flag_sends_nothing(self, mock_fetch):
        """When KPLER_OWNERSHIP_ENABLED is false, live mode prints clear error and sends nothing."""
        out = io.StringIO()
        err = io.StringIO()
        call_command("enrich_ownership", "--live", "--apply", stdout=out, stderr=err)

        mock_fetch.assert_not_called()
        self.assertIn("Live Kpler ownership enrichment is disabled", err.getvalue())

    @override_settings(KPLER_OWNERSHIP_ENABLED=True, KPLER_OWNERSHIP_MONTHLY_IMO_CAP=2)
    @patch("apps.enrichment.management.commands.enrich_ownership.fetch_vessels")
    def test_quota_guard_stops(self, mock_fetch):
        """When monthly cap is already reached, stops immediately with a clear message."""
        now = timezone.now()
        Vessel.objects.create(mmsi="111", imo="9111111", name="V1", ownership_checked_at=now)
        Vessel.objects.create(mmsi="222", imo="9222222", name="V2", ownership_checked_at=now)

        # 3rd vessel needing enrichment
        v3 = Vessel.objects.create(mmsi="333", imo="9333333", name="V3")
        Opportunity.objects.create(vessel=v3, port=self.port, zone="anchorage", score=40, stage="detected")

        out = io.StringIO()
        call_command("enrich_ownership", "--live", "--apply", stdout=out)

        mock_fetch.assert_not_called()
        self.assertIn("Monthly quota limit reached", out.getvalue())

    @override_settings(KPLER_OWNERSHIP_ENABLED=True)
    @patch("apps.enrichment.management.commands.enrich_ownership.fetch_vessels")
    def test_error_stops_run_and_saves_nothing_for_batch(self, mock_fetch):
        """Provider error stops the run immediately and saves nothing for that batch."""
        v = Vessel.objects.create(mmsi="100000001", imo="9146297", name="TARGET")
        Opportunity.objects.create(vessel=v, port=self.port, zone="anchorage", score=50, stage="detected")

        mock_fetch.side_effect = KplerAccessError("Vessels particulars and ownership are not enabled for this key")

        out = io.StringIO()
        err = io.StringIO()
        call_command("enrich_ownership", "--live", "--apply", stdout=out, stderr=err)

        self.assertIn("Kpler Access Error", err.getvalue())
        self.assertIn("Stopping run immediately", err.getvalue())

        v.refresh_from_db()
        self.assertIsNone(v.ownership_checked_at)
        self.assertEqual(VesselRelationship.objects.filter(vessel=v).count(), 0)

    @override_settings(KPLER_OWNERSHIP_ENABLED=False)
    def test_from_file_works_with_flag_off(self):
        """--from-file works and enriches vessels even when KPLER_OWNERSHIP_ENABLED is false."""
        v = Vessel.objects.create(mmsi="240123000", imo="9146297", name="OLD NAME")

        out = io.StringIO()
        call_command("enrich_ownership", f"--from-file={self.fixture_path}", stdout=out)

        self.assertIn("Ownership Enrichment Summary (From File)", out.getvalue())
        v.refresh_from_db()
        self.assertEqual(v.name, "PACIFIC EXPLORER")
        self.assertIsNotNone(v.ownership_checked_at)
        self.assertEqual(VesselRelationship.objects.filter(vessel=v).count(), 6)

