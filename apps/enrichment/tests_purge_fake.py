"""Tests for purge_fake_fixture_data (cleanup of the invented fixture rows)."""
import io
import json
from pathlib import Path

from django.core.management import call_command
from django.test import TestCase

from apps.companies.models import Company
from apps.observations.models import VesselObservation
from apps.opportunities.models import Opportunity
from apps.ports.models import Port
from apps.relationships.models import VesselRelationship
from apps.vessels.models import Vessel

TRIMMED = (
    Path(__file__).resolve().parent.parent.parent
    / "integrations" / "kpler" / "tests" / "fixtures" / "kpler_sample_trimmed.json"
)


def _run(*args):
    out = io.StringIO()
    call_command("purge_fake_fixture_data", *args, stdout=out)
    return out.getvalue()


class PurgeFakeFixtureDataTests(TestCase):
    def setUp(self):
        self.port = Port.objects.create(
            name="Singapore", un_locode="SGSIN", latitude=1.29, longitude=103.85,
            anchorage_latitude=1.30, anchorage_longitude=103.90, geofence_radius_km=40,
        )
        # What the invented fixture left behind
        self.real_vessel = Vessel.objects.create(
            mmsi="370014000", imo="9146297", name="PACIFIC EXPLORER", flag="Greece",
            grt=28000, dwt=48000, last_dry_dock="2023-05-15", last_renewal_survey="2023-05-20",
        )
        self.kanha = Vessel.objects.create(mmsi="257123000", imo="9308766", name="NORDIC STAR")
        self.fake_a = Vessel.objects.create(mmsi="356123000", imo="9456789", name="EASTERN PHOENIX")
        self.fake_b = Vessel.objects.create(mmsi="636123000", imo="9876543", name="SEA BREEZE")

        self.fake_company = Company.objects.create(name="Pacific Maritime Ltd", company_type="owner")
        self.fake_company_2 = Company.objects.create(name="Phoenix Shipping Lines Co", company_type="owner")
        self.real_company = Company.objects.create(name="PROVIDENCE SHIP MANAGEMENT INDIA PVT LTD")
        for vessel, company, role in [
            (self.real_vessel, self.fake_company, "registered_owner"),
            (self.fake_a, self.fake_company_2, "registered_owner"),
        ]:
            VesselRelationship.objects.create(
                vessel=vessel, company=company, role=role, source="kpler:file")
        self.real_rel = VesselRelationship.objects.create(
            vessel=self.real_vessel, company=self.real_company, role="technical_manager", source="kpler:file")

    def test_dry_run_changes_nothing_and_lists_everything(self):
        text = _run()
        self.assertIn("DRY-RUN", text)
        self.assertIn("Vessel to delete", text)
        self.assertIn("EASTERN PHOENIX", text)
        self.assertIn("Pacific Maritime Ltd", text)
        self.assertEqual(Vessel.objects.count(), 4)
        self.assertEqual(Company.objects.count(), 3)
        self.assertEqual(VesselRelationship.objects.count(), 3)
        self.real_vessel.refresh_from_db()
        self.assertEqual(str(self.real_vessel.last_dry_dock), "2023-05-15")

    def test_apply_removes_only_the_fake_set(self):
        _run("--apply")
        self.assertFalse(Vessel.objects.filter(pk__in=[self.fake_a.pk, self.fake_b.pk]).exists())
        self.assertFalse(Company.objects.filter(pk__in=[self.fake_company.pk, self.fake_company_2.pk]).exists())
        # Real vessels stay, real company and its relationship stay
        self.assertTrue(Vessel.objects.filter(pk=self.real_vessel.pk).exists())
        self.assertTrue(Vessel.objects.filter(pk=self.kanha.pk).exists())
        self.assertTrue(Company.objects.filter(pk=self.real_company.pk).exists())
        self.assertTrue(VesselRelationship.objects.filter(pk=self.real_rel.pk).exists())
        self.assertEqual(VesselRelationship.objects.count(), 1)

    def test_apply_clears_only_the_invented_survey_dates(self):
        _run("--apply")
        self.real_vessel.refresh_from_db()
        self.assertIsNone(self.real_vessel.last_dry_dock)
        self.assertIsNone(self.real_vessel.last_renewal_survey)

    def test_a_different_survey_date_is_left_alone(self):
        self.real_vessel.last_dry_dock = "2024-01-01"
        self.real_vessel.save()
        _run("--apply")
        self.real_vessel.refresh_from_db()
        self.assertEqual(str(self.real_vessel.last_dry_dock), "2024-01-01")
        self.assertIsNone(self.real_vessel.last_renewal_survey)

    def test_fake_vessel_with_an_opportunity_is_kept(self):
        Opportunity.objects.create(vessel=self.fake_b, port=self.port, zone="anchorage", stage="detected")
        text = _run("--apply")
        self.assertIn("KEEP vessel", text)
        self.assertTrue(Vessel.objects.filter(pk=self.fake_b.pk).exists())
        self.assertFalse(Vessel.objects.filter(pk=self.fake_a.pk).exists())

    def test_fake_vessel_with_an_observation_is_kept(self):
        from django.utils import timezone
        VesselObservation.objects.create(
            vessel=self.fake_b, latitude=1.0, longitude=103.0, source="test", timestamp=timezone.now())
        _run("--apply")
        self.assertTrue(Vessel.objects.filter(pk=self.fake_b.pk).exists())

    def test_company_used_by_a_non_fake_relationship_is_kept(self):
        """A person linked the same company on another vessel by hand: keep the company."""
        other = Vessel.objects.create(mmsi="999111222", imo="9111111", name="REAL OTHER")
        manual = VesselRelationship.objects.create(
            vessel=other, company=self.fake_company, role="owner", source="manual")
        text = _run("--apply")
        self.assertIn("KEEP company", text)
        self.assertTrue(Company.objects.filter(pk=self.fake_company.pk).exists())
        self.assertTrue(VesselRelationship.objects.filter(pk=manual.pk).exists())
        # the fake-sourced link on the real vessel is still removed
        self.assertFalse(
            VesselRelationship.objects.filter(vessel=self.real_vessel, company=self.fake_company).exists())

    def test_relationship_from_another_source_is_never_deleted(self):
        other = Vessel.objects.create(mmsi="999111333", imo="9111112", name="REAL OTHER 2")
        keep = VesselRelationship.objects.create(
            vessel=other, company=self.fake_company_2, role="owner", source="manual")
        _run("--apply")
        self.assertTrue(VesselRelationship.objects.filter(pk=keep.pk).exists())

    def test_second_apply_changes_nothing_after_enrichment_restores_real_values(self):
        _run("--apply")
        call_command(
            "enrich_ownership", f"--from-file={TRIMMED}", stdout=io.StringIO())
        self.real_vessel.refresh_from_db()
        self.kanha.refresh_from_db()
        self.assertEqual(self.real_vessel.name, "BLPL FAITH")
        self.assertEqual(self.real_vessel.flag, "Panama")
        self.assertEqual(self.real_vessel.grt, 8299.0)
        self.assertIsNone(self.real_vessel.last_dry_dock)
        self.assertEqual(self.kanha.name, "KANHA")
        self.assertEqual(self.kanha.mmsi, "511101460")  # fake MMSI replaced by the real one
        self.assertEqual(self.kanha.flag, "Palau")
        self.assertEqual(str(self.kanha.last_dry_dock), "2025-08-30")

        before = (Vessel.objects.count(), Company.objects.count(), VesselRelationship.objects.count())
        text = _run("--apply")
        self.assertIn("Nothing to clean up", text)
        self.assertEqual(
            (Vessel.objects.count(), Company.objects.count(), VesselRelationship.objects.count()), before)

    def test_warns_when_real_vessels_still_carry_invented_names(self):
        text = _run()
        self.assertIn("still has the invented name PACIFIC EXPLORER", text)
        self.assertIn("still has the invented name NORDIC STAR", text)

    def test_real_fixture_enrichment_leaves_no_trace_of_the_invented_data(self):
        """After purge + real enrichment, none of the invented names remain anywhere."""
        _run("--apply")
        call_command("enrich_ownership", f"--from-file={TRIMMED}", stdout=io.StringIO())
        invented = {"PACIFIC EXPLORER", "NORDIC STAR", "EASTERN PHOENIX", "SEA BREEZE"}
        self.assertFalse(Vessel.objects.filter(name__in=invented).exists())
        for name in ("Pacific Maritime Ltd", "Nordic Tankers KS", "Phoenix Shipping Lines Co"):
            self.assertFalse(Company.objects.filter(name=name).exists())
        # The real fixture is still the one on disk
        data = json.loads(TRIMMED.read_text(encoding="utf-8"))
        self.assertEqual(len(data["data"]["vessels"]["nodes"]), 4)
