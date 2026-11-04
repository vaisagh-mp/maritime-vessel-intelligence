from django.test import TestCase
from django.db import IntegrityError

from apps.common.constants import (
    RELATIONSHIP_ROLE_BENEFICIAL_OWNER,
    RELATIONSHIP_ROLE_ISM_MANAGER,
    RELATIONSHIP_ROLE_TECHNICAL_MANAGER,
)
from apps.companies.models import Company
from apps.vessels.models import Vessel

from .models import VesselRelationship


class VesselRelationshipTests(TestCase):
    def setUp(self):
        self.vessel = Vessel.objects.create(mmsi="123", name="TEST VESSEL")
        self.company = Company.objects.create(name="Verital Marine", company_type="manager")

    def test_unverified_by_default(self):
        rel = VesselRelationship.objects.create(
            vessel=self.vessel, company=self.company, role="manager", source="test-source"
        )
        self.assertFalse(rel.verified)

    def test_duplicate_vessel_company_role_rejected(self):
        VesselRelationship.objects.create(
            vessel=self.vessel, company=self.company, role="manager", source="test-source"
        )
        with self.assertRaises(IntegrityError):
            VesselRelationship.objects.create(
                vessel=self.vessel, company=self.company, role="manager", source="test-source"
            )

    def test_is_current_default_is_true(self):
        rel = VesselRelationship.objects.create(
            vessel=self.vessel, company=self.company, role="manager", source="test-source"
        )
        self.assertTrue(rel.is_current)

    def test_new_roles_are_valid_choices(self):
        for role in [
            RELATIONSHIP_ROLE_TECHNICAL_MANAGER,
            RELATIONSHIP_ROLE_ISM_MANAGER,
            RELATIONSHIP_ROLE_BENEFICIAL_OWNER,
        ]:
            c = Company.objects.create(name=f"Company {role}", company_type="manager")
            rel = VesselRelationship.objects.create(
                vessel=self.vessel, company=c, role=role, source="test-source"
            )
            # full_clean verifies choices validation
            rel.full_clean()
            self.assertEqual(rel.role, role)
