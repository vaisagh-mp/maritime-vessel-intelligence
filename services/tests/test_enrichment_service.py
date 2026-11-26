"""Tests for enrich_vessel service, using REAL Kpler data (4 vessels trimmed,
unmodified, from Kpler's own sample file: kpler_sample_trimmed.json)."""
import copy
import json
from pathlib import Path

from django.test import TestCase

from apps.common.constants import (
    PRIORITY_HIGH,
    PRIORITY_LOW,
    PRIORITY_MEDIUM,
    RELATIONSHIP_ROLE_BENEFICIAL_OWNER,
    RELATIONSHIP_ROLE_REGISTERED_OWNER,
    RELATIONSHIP_ROLE_TECHNICAL_MANAGER,
    STAGE_WON,
    ZONE_ANCHORAGE,
)
from apps.companies.models import Company
from apps.opportunities.models import Opportunity, OpportunityStageChange
from apps.ports.models import Port
from apps.relationships.models import VesselRelationship
from apps.vessels.models import Vessel
from integrations.kpler.vessel_parser import parse_vessel_node
from services.enrichment_service import enrich_vessel, normalize_company_name

# Real IMOs in the fixture
BLPL_FAITH = "9146297"      # managers with website and email
KANHA = "9308766"           # technical manager with no contacts, owner with email
WAN_HAI_501 = "9294848"
BAILIAN_STAR = "9250218"    # one company in five roles, no contacts

PROVIDENCE = "PROVIDENCE SHIP MANAGEMENT INDIA PVT LTD"
BLPL_SINGAPORE = "BLPL SINGAPORE PTE LTD"
TRANSWORLD = "TRANSWORLD HOLDINGS LTD TRANSWORLD GROUP"


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
            / "kpler_sample_trimmed.json"
        )
        with open(fixture_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        # Kpler sends the IMO as a number in the raw node; key by string.
        cls.raw_nodes = {
            str(node["identifier"]["imo"]): node
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

    def _parsed(self, imo):
        return parse_vessel_node(self.raw_nodes[imo])

    # ------------------------------------------------------------------
    # Create path and idempotence
    # ------------------------------------------------------------------

    def test_create_path(self):
        """Vessel particulars, companies, and relationships are created from the real node."""
        vessel = Vessel.objects.create(mmsi="370014000", imo=BLPL_FAITH, name="OLD NAME")

        res = enrich_vessel(self._parsed(BLPL_FAITH))
        self.assertIsNotNone(res)
        # Providence is shared by commercial manager, operator, technical and ISM manager
        self.assertEqual(res["created_companies"], 3)
        self.assertEqual(res["created_relationships"], 6)

        vessel.refresh_from_db()
        self.assertEqual(vessel.name, "BLPL FAITH")
        self.assertEqual(vessel.flag, "Panama")
        self.assertEqual(vessel.grt, 8299.0)
        self.assertEqual(vessel.dwt, 10299.0)
        self.assertEqual(vessel.vessel_type, "Container")
        self.assertIsNotNone(vessel.ownership_checked_at)

        rels = VesselRelationship.objects.filter(vessel=vessel, is_current=True)
        self.assertEqual(rels.count(), 6)

    def test_idempotent_second_run_changes_nothing(self):
        Vessel.objects.create(mmsi="370014000", imo=BLPL_FAITH, name="BLPL FAITH")
        parsed = self._parsed(BLPL_FAITH)

        res1 = enrich_vessel(parsed)
        self.assertEqual(res1["created_companies"], 3)
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
        Company.objects.create(
            name=PROVIDENCE,
            country="INDIA",
            website="https://custom-hand-edited.com",
            email="custom@hand-edited.com",
            address="Custom Address 123",
            priority=PRIORITY_HIGH,
        )
        Vessel.objects.create(mmsi="370014000", imo=BLPL_FAITH, name="BLPL FAITH")

        enrich_vessel(self._parsed(BLPL_FAITH))

        comp = Company.objects.get(name=PROVIDENCE)
        self.assertEqual(comp.website, "https://custom-hand-edited.com")
        self.assertEqual(comp.email, "custom@hand-edited.com")
        self.assertEqual(comp.address, "Custom Address 123")
        self.assertEqual(comp.priority, PRIORITY_HIGH)

    def test_manager_changed_to_another_company_closes_old_relationship(self):
        vessel = Vessel.objects.create(mmsi="370014000", imo=BLPL_FAITH, name="BLPL FAITH")
        old_manager = Company.objects.create(name="Old Manager Co", company_type="manager")
        old_rel = VesselRelationship.objects.create(
            vessel=vessel,
            company=old_manager,
            role=RELATIONSHIP_ROLE_TECHNICAL_MANAGER,
            is_current=True,
            source="manual",
        )

        res = enrich_vessel(self._parsed(BLPL_FAITH))
        self.assertGreaterEqual(res["closed_relationships"], 1)

        old_rel.refresh_from_db()
        self.assertFalse(old_rel.is_current)
        self.assertIsNotNone(old_rel.end_date)

        new_rel = VesselRelationship.objects.get(
            vessel=vessel, role=RELATIONSHIP_ROLE_TECHNICAL_MANAGER, is_current=True
        )
        self.assertEqual(new_rel.company.name, PROVIDENCE)

    # ------------------------------------------------------------------
    # Particulars
    # ------------------------------------------------------------------

    def test_particulars_never_overwritten_by_null(self):
        """Kpler has no dry-dock dates for BLPL FAITH; an existing value is kept."""
        vessel = Vessel.objects.create(
            mmsi="370014000",
            imo=BLPL_FAITH,
            name="BLPL FAITH",
            last_dry_dock="2020-01-01",
            last_renewal_survey="2020-02-02",
        )
        parsed = self._parsed(BLPL_FAITH)
        self.assertIsNone(parsed["particulars"]["last_dry_dock"])
        self.assertIsNone(parsed["particulars"]["last_renewal_survey"])

        enrich_vessel(parsed)

        vessel.refresh_from_db()
        self.assertEqual(str(vessel.last_dry_dock), "2020-01-01")
        self.assertEqual(str(vessel.last_renewal_survey), "2020-02-02")
        self.assertEqual(vessel.callsign, "3ERD6")  # real value was filled

    def test_mmsi_placeholder_is_replaced_by_the_real_mmsi(self):
        """A vessel stored with a wrong or placeholder MMSI gets the registered one."""
        vessel = Vessel.objects.create(mmsi="999308766", imo=KANHA, name="IMO 9308766")
        enrich_vessel(self._parsed(KANHA))
        vessel.refresh_from_db()
        self.assertEqual(vessel.mmsi, "511101460")
        self.assertEqual(vessel.name, "KANHA")
        self.assertEqual(vessel.flag, "Palau")

    def test_mmsi_kept_when_it_belongs_to_another_vessel(self):
        """MMSI is unique: a clash never crashes and never steals the other vessel's MMSI."""
        Vessel.objects.create(mmsi="511101460", imo="1111111", name="OTHER")
        vessel = Vessel.objects.create(mmsi="999308766", imo=KANHA, name="IMO 9308766")

        res = enrich_vessel(self._parsed(KANHA))

        self.assertIsNotNone(res)
        vessel.refresh_from_db()
        self.assertEqual(vessel.mmsi, "999308766")
        self.assertEqual(vessel.name, "KANHA")  # the rest was still enriched

    def test_ownership_checked_at_set_when_no_parties(self):
        """ownership_checked_at is stamped even when Kpler returns no parties."""
        vessel = Vessel.objects.create(mmsi="352003109", imo=BAILIAN_STAR, name="BAILIAN STAR")
        self.assertIsNone(vessel.ownership_checked_at)

        node = copy.deepcopy(self.raw_nodes[BAILIAN_STAR])
        node["management"] = {}
        parsed = parse_vessel_node(node)
        self.assertEqual(len(parsed["parties"]), 0)

        enrich_vessel(parsed)

        vessel.refresh_from_db()
        self.assertIsNotNone(vessel.ownership_checked_at)

    # ------------------------------------------------------------------
    # Rescoring
    # ------------------------------------------------------------------

    def test_rescoring_raises_score_when_manager_with_contacts_appears(self):
        """An enriched manager with website and email now adds points on its own,
        without anyone setting the company priority."""
        vessel = Vessel.objects.create(
            mmsi="370014000", imo=BLPL_FAITH, name="BLPL FAITH", vessel_type="Container", grt=8299
        )
        opp = Opportunity.objects.create(
            vessel=vessel, port=self.port, zone=ZONE_ANCHORAGE, score=30, stage="detected"
        )
        initial_score = opp.score

        enrich_vessel(self._parsed(BLPL_FAITH))

        opp.refresh_from_db()
        self.assertGreater(opp.score, initial_score)
        self.assertIn("technical manager with contacts 20", opp.lead_reason)
        self.assertIn("registered owner with email 8", opp.lead_reason)
        # New company priority stays "medium" (not high): no priority bonus
        self.assertNotIn("high-priority", opp.lead_reason)

    def test_best_manager_is_taken_across_roles_for_kanha(self):
        """KANHA: the technical and ISM manager (ONTARIO MARINE SERVICES) have no
        website or email, but the commercial manager (KANHA SHIPPING INC) has an
        email. The best manager counts (12), and the registered owner adds 8."""
        vessel = Vessel.objects.create(mmsi="511101460", imo=KANHA, name="KANHA", grt=8351)
        opp = Opportunity.objects.create(
            vessel=vessel, port=self.port, zone=ZONE_ANCHORAGE, score=30, stage="detected"
        )
        enrich_vessel(self._parsed(KANHA))
        opp.refresh_from_db()
        self.assertIn("commercial manager with partial contacts 12", opp.lead_reason)
        self.assertIn("registered owner with email 8", opp.lead_reason)

    def test_bailian_star_all_roles_are_one_company_with_no_contacts(self):
        """BAILIAN STAR: one company in five roles and no website or email -> manager name only (6)."""
        vessel = Vessel.objects.create(mmsi="352003109", imo=BAILIAN_STAR, name="BAILIAN STAR", grt=39727)
        opp = Opportunity.objects.create(
            vessel=vessel, port=self.port, zone=ZONE_ANCHORAGE, score=30, stage="detected"
        )
        res = enrich_vessel(self._parsed(BAILIAN_STAR))
        self.assertEqual(res["created_companies"], 1)
        self.assertEqual(res["created_relationships"], 5)
        opp.refresh_from_db()
        self.assertIn("technical manager name only 6", opp.lead_reason)
        self.assertIn("registered owner name only 4", opp.lead_reason)

    def test_no_stage_history_written_by_rescore(self):
        vessel = Vessel.objects.create(mmsi="370014000", imo=BLPL_FAITH, name="BLPL FAITH")
        Opportunity.objects.create(
            vessel=vessel, port=self.port, zone=ZONE_ANCHORAGE, score=30, stage="detected"
        )

        history_count_before = OpportunityStageChange.objects.count()
        enrich_vessel(self._parsed(BLPL_FAITH))

        self.assertEqual(OpportunityStageChange.objects.count(), history_count_before)

    # ------------------------------------------------------------------
    # Roles and priority
    # ------------------------------------------------------------------

    def test_different_registered_and_beneficial_owners_kept_without_churn(self):
        """Different registered and beneficial owners both stay current across runs."""
        vessel = Vessel.objects.create(mmsi="370014000", imo=BLPL_FAITH, name="BLPL FAITH")
        parsed = self._parsed(BLPL_FAITH)

        enrich_vessel(parsed)
        reg_rel1 = VesselRelationship.objects.get(vessel=vessel, role=RELATIONSHIP_ROLE_REGISTERED_OWNER)
        ben_rel1 = VesselRelationship.objects.get(vessel=vessel, role=RELATIONSHIP_ROLE_BENEFICIAL_OWNER)
        self.assertTrue(reg_rel1.is_current)
        self.assertTrue(ben_rel1.is_current)
        self.assertNotEqual(reg_rel1.company_id, ben_rel1.company_id)
        self.assertEqual(reg_rel1.company.name, BLPL_SINGAPORE)
        self.assertEqual(ben_rel1.company.name, TRANSWORLD)

        res2 = enrich_vessel(parsed)
        self.assertEqual(res2["closed_relationships"], 0)
        self.assertEqual(res2["created_relationships"], 0)

        reg_rel2 = VesselRelationship.objects.get(vessel=vessel, role=RELATIONSHIP_ROLE_REGISTERED_OWNER)
        ben_rel2 = VesselRelationship.objects.get(vessel=vessel, role=RELATIONSHIP_ROLE_BENEFICIAL_OWNER)
        self.assertEqual(reg_rel2.pk, reg_rel1.pk)
        self.assertEqual(ben_rel2.pk, ben_rel1.pk)
        self.assertTrue(reg_rel2.is_current)
        self.assertTrue(ben_rel2.is_current)

    def test_company_priority_medium_only_when_both_website_and_email_present(self):
        """New company gets priority=medium only when website AND email are present, else low."""
        Vessel.objects.create(mmsi="370014000", imo=BLPL_FAITH, name="BLPL FAITH")
        enrich_vessel(self._parsed(BLPL_FAITH))
        both = Company.objects.get(name=PROVIDENCE)
        self.assertTrue(both.website)
        self.assertTrue(both.email)
        self.assertEqual(both.priority, PRIORITY_MEDIUM)

        Vessel.objects.create(mmsi="511101460", imo=KANHA, name="KANHA")
        enrich_vessel(self._parsed(KANHA))
        email_only = Company.objects.get(name="KANHA SHIPPING INC")
        self.assertTrue(email_only.email)
        self.assertFalse(email_only.website)
        self.assertEqual(email_only.priority, PRIORITY_LOW)

        neither = Company.objects.get(name="ONTARIO MARINE SERVICES")
        self.assertFalse(neither.website)
        self.assertFalse(neither.email)
        self.assertEqual(neither.priority, PRIORITY_LOW)

    def test_person_edited_priority_is_never_overwritten(self):
        Company.objects.create(name=BLPL_SINGAPORE, country="SINGAPORE", priority=PRIORITY_HIGH)
        Vessel.objects.create(mmsi="370014000", imo=BLPL_FAITH, name="BLPL FAITH")
        enrich_vessel(self._parsed(BLPL_FAITH))

        comp = Company.objects.get(name=BLPL_SINGAPORE)
        self.assertEqual(comp.priority, PRIORITY_HIGH)

    def test_scoring_owner_factor_fires_for_enriched_registered_owner(self):
        """Enriching a registered owner links the vessel to a company that has a
        won sister-vessel lead, so the existing-relationship signal fires (+30)."""
        owner = Company.objects.create(
            name=BLPL_SINGAPORE,
            country="SINGAPORE",
            company_type="owner",
            priority=PRIORITY_MEDIUM,
        )
        sister_vessel = Vessel.objects.create(mmsi="999000111", name="SISTER VESSEL")
        VesselRelationship.objects.create(
            vessel=sister_vessel,
            company=owner,
            role=RELATIONSHIP_ROLE_REGISTERED_OWNER,
            source="manual",
            is_current=True,
        )
        Opportunity.objects.create(
            vessel=sister_vessel, port=self.port, zone=ZONE_ANCHORAGE, stage=STAGE_WON, score=90
        )

        target_vessel = Vessel.objects.create(
            mmsi="370014000", imo=BLPL_FAITH, name="BLPL FAITH", vessel_type="Container", grt=8299
        )
        opp = Opportunity.objects.create(
            vessel=target_vessel, port=self.port, zone=ZONE_ANCHORAGE, stage="detected", score=30
        )
        initial_score = opp.score

        enrich_vessel(self._parsed(BLPL_FAITH))

        opp.refresh_from_db()
        self.assertGreaterEqual(opp.score, initial_score + 30)
        self.assertIn("existing relationship 30", opp.lead_reason)

    # ------------------------------------------------------------------
    # Name matching
    # ------------------------------------------------------------------

    def test_normalize_company_name_strips_suffixes_and_punctuation(self):
        self.assertEqual(
            normalize_company_name("Providence Ship Management India Pvt. Ltd."),
            "PROVIDENCE SHIP MANAGEMENT INDIA PVT",
        )
        self.assertEqual(normalize_company_name("BLPL SINGAPORE PTE LTD"), "BLPL SINGAPORE")
        self.assertEqual(normalize_company_name(""), "")
