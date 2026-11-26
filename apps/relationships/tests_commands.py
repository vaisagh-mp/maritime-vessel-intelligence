"""Tests for fix_legacy_owner_roles management command."""
from io import StringIO
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from apps.common.constants import (
    RELATIONSHIP_ROLE_OWNER,
    RELATIONSHIP_ROLE_REGISTERED_OWNER,
)
from apps.companies.models import Company
from apps.relationships.models import VesselRelationship
from apps.vessels.models import Vessel


class FixLegacyOwnerRolesCommandTests(TestCase):
    def setUp(self):
        self.vessel = Vessel.objects.create(mmsi="111222333", imo="9111222", name="TEST VESSEL")
        self.company = Company.objects.create(name="Owner Maritime Ltd", company_type="owner")

    def test_dry_run_changes_nothing(self):
        """In dry-run mode, legacy owner relationship remains is_current=True and end_date is None."""
        legacy_rel = VesselRelationship.objects.create(
            vessel=self.vessel,
            company=self.company,
            role=RELATIONSHIP_ROLE_OWNER,
            source="kpler:file",
            is_current=True,
        )
        reg_rel = VesselRelationship.objects.create(
            vessel=self.vessel,
            company=self.company,
            role=RELATIONSHIP_ROLE_REGISTERED_OWNER,
            source="kpler:file",
            is_current=True,
        )

        out = StringIO()
        call_command("fix_legacy_owner_roles", "--dry-run", stdout=out)
        output = out.getvalue()

        self.assertIn("1 legacy Kpler 'owner' relationship(s)", output)
        self.assertIn("[DRY-RUN]", output)

        legacy_rel.refresh_from_db()
        self.assertTrue(legacy_rel.is_current)
        self.assertIsNone(legacy_rel.end_date)

        reg_rel.refresh_from_db()
        self.assertTrue(reg_rel.is_current)

    def test_apply_closes_only_duplicates(self):
        """With --apply, legacy owner relationship is closed (is_current=False, end_date set), registered_owner is untouched."""
        legacy_rel = VesselRelationship.objects.create(
            vessel=self.vessel,
            company=self.company,
            role=RELATIONSHIP_ROLE_OWNER,
            source="kpler:live",
            is_current=True,
        )
        reg_rel = VesselRelationship.objects.create(
            vessel=self.vessel,
            company=self.company,
            role=RELATIONSHIP_ROLE_REGISTERED_OWNER,
            source="kpler:live",
            is_current=True,
        )

        out = StringIO()
        call_command("fix_legacy_owner_roles", "--apply", stdout=out)
        output = out.getvalue()

        self.assertIn("[APPLY complete] Successfully closed 1 legacy duplicate", output)

        legacy_rel.refresh_from_db()
        self.assertFalse(legacy_rel.is_current)
        self.assertEqual(legacy_rel.end_date, timezone.now().date())

        reg_rel.refresh_from_db()
        self.assertTrue(reg_rel.is_current)

    def test_second_apply_changes_nothing(self):
        """Second run with --apply is idempotent: finds 0 duplicates to close."""
        legacy_rel = VesselRelationship.objects.create(
            vessel=self.vessel,
            company=self.company,
            role=RELATIONSHIP_ROLE_OWNER,
            source="kpler:file",
            is_current=True,
        )
        VesselRelationship.objects.create(
            vessel=self.vessel,
            company=self.company,
            role=RELATIONSHIP_ROLE_REGISTERED_OWNER,
            source="kpler:file",
            is_current=True,
        )

        # First run
        call_command("fix_legacy_owner_roles", "--apply", stdout=StringIO())

        # Second run
        out2 = StringIO()
        call_command("fix_legacy_owner_roles", "--apply", stdout=out2)
        output2 = out2.getvalue()

        self.assertIn("Found 0 legacy Kpler 'owner' relationship(s)", output2)
        self.assertIn("No duplicate legacy owner relationships found to close.", output2)

    def test_rows_from_other_sources_untouched(self):
        """Relationships with sources other than kpler are never closed."""
        datadocked_rel = VesselRelationship.objects.create(
            vessel=self.vessel,
            company=self.company,
            role=RELATIONSHIP_ROLE_OWNER,
            source="datadocked.com",
            is_current=True,
        )
        manual_rel = VesselRelationship.objects.create(
            vessel=self.vessel,
            company=self.company,
            role=RELATIONSHIP_ROLE_REGISTERED_OWNER,
            source="manual",
            is_current=True,
        )

        out = StringIO()
        call_command("fix_legacy_owner_roles", "--apply", stdout=out)
        output = out.getvalue()

        self.assertIn("Found 0 legacy Kpler 'owner' relationship(s)", output)

        datadocked_rel.refresh_from_db()
        self.assertTrue(datadocked_rel.is_current)
        self.assertIsNone(datadocked_rel.end_date)

    def test_legacy_owner_without_matching_registered_owner_untouched(self):
        """A Kpler owner relationship that has no corresponding registered_owner relationship is kept."""
        other_comp = Company.objects.create(name="Sole Owner Corp", company_type="owner")
        sole_rel = VesselRelationship.objects.create(
            vessel=self.vessel,
            company=other_comp,
            role=RELATIONSHIP_ROLE_OWNER,
            source="kpler:file",
            is_current=True,
        )

        out = StringIO()
        call_command("fix_legacy_owner_roles", "--apply", stdout=out)
        output = out.getvalue()

        self.assertIn("Found 0 legacy Kpler 'owner' relationship(s)", output)

        sole_rel.refresh_from_db()
        self.assertTrue(sole_rel.is_current)
        self.assertIsNone(sole_rel.end_date)

