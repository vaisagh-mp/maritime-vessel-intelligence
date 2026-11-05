"""Tests for enrich_vessel service."""
import json
from datetime import timedelta
from pathlib import Path
from django.test import TestCase
from django.utils import timezone

from apps.common.constants import (
    PRIORITY_HIGH,
    PRIORITY_MEDIUM,
    RELATIONSHIP_ROLE_ISM_MANAGER,
    RELATIONSHIP_ROLE_TECHNICAL_MANAGER,
    ZONE_ANCHORAGE,
)
from apps.companies.models import Company
from apps.opportunities.models import Opportunity, OpportunityStageChange
from apps.ports.models import Port
from apps.relationships.models import VesselRelationship
from apps.vessels.models import Vessel
from integrations.kpler.vessel_parser import parse_vessel_node
from services.enrichment_service import enrich_vessel, normalize_company_name


class EnrichmentServiceTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        fixture_path = (
            Path(__file__).resolve().parent.parent.parent
            / "integrations"
            / "kpler"
            / "tests"
            / "fixtures"
            / "kpler_sample.json"
        )
        with open(fixture_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        cls.raw_nodes = {
            node["identifier"]["imo"]: node
            for node in data["data"]["vessels"]["nodes"]
        }

    def setUp(self):
        self.port = Port.objects.create(
            name="Singapore",
            un_locode="SGSIN",
            latitude=1.29,
            longitude=103.85,
            anchorage_latitude=1.30,
            anchorage_longitude=103.90,
            geofence_radius_km=40,
        )

    def test_create_path(self):
        """Vessel particulars, companies, and relationships are created from parsed node."""
        vessel = Vessel.objects.create(
            mmsi="240123000", imo="9146297", name="OLD NAME"
        )
        parsed = parse_vessel_node(self.raw_nodes["9146297"])

        res = enrich_vessel(parsed)
        self.assertIsNotNone(res)
        self.assertEqual(res["created_companies"], 5)  # Pacific Shipmanagement is shared between tech & ism
        self.assertEqual(res["created_relationships"], 6)

        vessel.refresh_from_db()
        self.assertEqual(vessel.name, "PACIFIC EXPLORER")
        self.assertEqual(vessel.flag, "Greece")
        self.assertEqual(vessel.grt, 28000.0)
        self.assertEqual(vessel.dwt, 48000.0)
        self.assertEqual(vessel.vessel_type, "Bulk Carrier")
        self.assertIsNotNone(vessel.ownership_checked_at)

        rels = VesselRelationship.objects.filter(vessel=vessel, is_current=True)
        self.assertEqual(rels.count(), 6)

    def test_idempotent_second_run_changes_nothing(self):
        """A second run with identical data creates no new companies or relationships."""
        vessel = Vessel.objects.create(mmsi="240123000", imo="9146297", name="PACIFIC EXPLORER")
        parsed = parse_vessel_node(self.raw_nodes["9146297"])

        res1 = enrich_vessel(parsed)
        self.assertEqual(res1["created_companies"], 5)
        self.assertEqual(res1["created_relationships"], 6)

        initial_comp_count = Company.objects.count()
        initial_rel_count = VesselRelationship.objects.count()

        res2 = enrich_vessel(parsed)
        self.assertEqual(res2["created_companies"], 0)
        self.assertEqual(res2["created_relationships"], 0)
        self.assertEqual(res2["closed_relationships"], 0)
        self.assertEqual(Company.objects.count(), initial_comp_count)
        self.assertEqual(VesselRelationship.objects.count(), initial_rel_count)

    def test_company_edited_by_hand_keeps_its_value(self):
        """User-edited company fields (email, website, address) are never overwritten."""
        # Pre-create company with custom values
        Company.objects.create(
            name="Pacific Shipmanagement Ltd",
            country="Cyprus",
            website="https://custom-hand-edited.com",
            email="custom@hand-edited.com",
            address="Custom Address 123",
            priority=PRIORITY_HIGH,
        )
        vessel = Vessel.objects.create(mmsi="240123000", imo="9146297", name="PACIFIC EXPLORER")
        parsed = parse_vessel_node(self.raw_nodes["9146297"])

        enrich_vessel(parsed)

        comp = Company.objects.get(name="Pacific Shipmanagement Ltd")
        self.assertEqual(comp.website, "https://custom-hand-edited.com")
        self.assertEqual(comp.email, "custom@hand-edited.com")
        self.assertEqual(comp.address, "Custom Address 123")
        self.assertEqual(comp.priority, PRIORITY_HIGH)

    def test_manager_changed_to_another_company_closes_old_relationship(self):
        """When manager changes, the previous relationship is closed (is_current=False, end_date set)."""
        vessel = Vessel.objects.create(mmsi="240123000", imo="9146297", name="PACIFIC EXPLORER")
        old_manager = Company.objects.create(name="Old Manager Co", company_type="manager")
        old_rel = VesselRelationship.objects.create(
            vessel=vessel,
            company=old_manager,
            role=RELATIONSHIP_ROLE_TECHNICAL_MANAGER,
            is_current=True,
            source="manual",
        )

        parsed = parse_vessel_node(self.raw_nodes["9146297"])
        res = enrich_vessel(parsed)

        self.assertGreaterEqual(res["closed_relationships"], 1)

        old_rel.refresh_from_db()
        self.assertFalse(old_rel.is_current)
        self.assertIsNotNone(old_rel.end_date)

        new_rel = VesselRelationship.objects.get(
            vessel=vessel, role=RELATIONSHIP_ROLE_TECHNICAL_MANAGER, is_current=True
        )
        self.assertEqual(new_rel.company.name, "Pacific Shipmanagement Ltd")

    def test_particulars_never_overwritten_by_null(self):
        """Existing vessel particulars are preserved when Kpler returns null/None."""
        vessel = Vessel.objects.create(
            mmsi="636123000",
            imo="9876543",
            name="SEA BREEZE",
            callsign="CALL123",
            ship_id="SHIP999",
            vessel_size_segment="Handysize",
            last_dry_dock="2020-01-01",
        )
        parsed = parse_vessel_node(self.raw_nodes["9876543"])
        # In vessel 4, callsign, ship_id, vessel_size_segment, last_dry_dock are null in Kpler
        self.assertIsNone(parsed["particulars"]["callsign"])
        self.assertIsNone(parsed["particulars"]["ship_id"])

        enrich_vessel(parsed)

        vessel.refresh_from_db()
        self.assertEqual(vessel.callsign, "CALL123")
        self.assertEqual(vessel.ship_id, "SHIP999")
        self.assertEqual(vessel.vessel_size_segment, "Handysize")
        self.assertEqual(str(vessel.last_dry_dock), "2020-01-01")

    def test_ownership_checked_at_set_when_no_parties(self):
        """ownership_checked_at is stamped even when Kpler node has no parties."""
        vessel = Vessel.objects.create(mmsi="636123000", imo="9876543", name="SEA BREEZE")
        self.assertIsNone(vessel.ownership_checked_at)

        parsed = parse_vessel_node(self.raw_nodes["9876543"])
        self.assertEqual(len(parsed["parties"]), 0)

        enrich_vessel(parsed)

        vessel.refresh_from_db()
        self.assertIsNotNone(vessel.ownership_checked_at)

    def test_rescoring_raises_score_when_manager_with_contacts_appears(self):
        """Enriching a vessel with a manager raises the open opportunity's score."""
        vessel = Vessel.objects.create(
            mmsi="240123000", imo="9146297", name="PACIFIC EXPLORER", vessel_type="Bulk Carrier", grt=28000
        )
        opp = Opportunity.objects.create(
            vessel=vessel, port=self.port, zone=ZONE_ANCHORAGE, score=30, stage="detected"
        )
        initial_score = opp.score

        # Pre-create manager with high priority so manager factor fires
        Company.objects.create(
            name="Pacific Shipmanagement Ltd",
            country="Cyprus",
            company_type="manager",
            priority=PRIORITY_HIGH,
        )

        parsed = parse_vessel_node(self.raw_nodes["9146297"])
        enrich_vessel(parsed)

        opp.refresh_from_db()
        self.assertGreater(opp.score, initial_score)

    def test_no_stage_history_written_by_rescore(self):
        """Opportunity rescoring during enrichment never creates OpportunityStageChange entries."""
        vessel = Vessel.objects.create(mmsi="240123000", imo="9146297", name="PACIFIC EXPLORER")
        opp = Opportunity.objects.create(
            vessel=vessel, port=self.port, zone=ZONE_ANCHORAGE, score=30, stage="detected"
        )

        history_count_before = OpportunityStageChange.objects.count()
        parsed = parse_vessel_node(self.raw_nodes["9146297"])
        enrich_vessel(parsed)

        self.assertEqual(OpportunityStageChange.objects.count(), history_count_before)
