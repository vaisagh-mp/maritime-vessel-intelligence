from django.test import TestCase
from django.db import IntegrityError

from apps.companies.models import Company
from apps.vessels.models import Vessel

from .models import VesselRelationship


class VesselRelationshipTests(TestCase):
    def setUp(self):
        self.vessel = Vessel.objects.create(mmsi="123", name="TEST VESSEL")
        self.company = Company.objects.create(name="Verital Marine", company_type="manager")

    def test_unverified_by_default(self):
        rel = VesselRelationship.objects.create(
            vessel=self.vessel, company=self.company, role="manager", source="datadocked.com"
        )
        self.assertFalse(rel.verified)

    def test_duplicate_vessel_company_role_rejected(self):
        VesselRelationship.objects.create(
            vessel=self.vessel, company=self.company, role="manager", source="datadocked.com"
        )
        with self.assertRaises(IntegrityError):
            VesselRelationship.objects.create(
                vessel=self.vessel, company=self.company, role="manager", source="datadocked.com"
            )
