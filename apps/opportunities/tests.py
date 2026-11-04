from django.contrib.auth.models import Group, User
from django.test import TestCase
from rest_framework.test import APIClient

from apps.ports.models import Port
from apps.vessels.models import Vessel

from .models import Opportunity


class OpportunityStagePatchTests(TestCase):
    def setUp(self):
        # All opportunity endpoints now require authentication + at least BD Manager role.
        bd_group, _ = Group.objects.get_or_create(name="BD Manager")
        self.bd_user = User.objects.create_user("bd_opp_tester", password="testpass")
        self.bd_user.groups.add(bd_group)

        self.vessel = Vessel.objects.create(mmsi="777", name="TEST VESSEL")
        self.port = Port.objects.create(
            name="Fujairah", un_locode="AEFJR", latitude=25.1, longitude=56.3,
            anchorage_latitude=25.15, anchorage_longitude=56.4, geofence_radius_km=45,
        )
        self.opp = Opportunity.objects.create(
            vessel=self.vessel, port=self.port, zone="anchorage", stage="detected"
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.bd_user)

    def test_patch_updates_only_stage(self):
        response = self.client.patch(
            f"/api/v1/opportunities/{self.opp.id}/", {"stage": "contacted"}, format="json"
        )
        self.assertEqual(response.status_code, 200)
        self.opp.refresh_from_db()
        self.assertEqual(self.opp.stage, "contacted")

    def test_put_not_allowed(self):
        # PUT is excluded from http_method_names — DRF returns 405 (Method Not Allowed)
        # before any permission class runs.
        response = self.client.put(
            f"/api/v1/opportunities/{self.opp.id}/", {"stage": "contacted"}, format="json"
        )
        self.assertEqual(response.status_code, 405)

    def test_is_inbound_default_is_false(self):
        self.assertFalse(self.opp.is_inbound)


class OpportunityPayloadAndQueryCountTests(TestCase):
    def setUp(self):
        bd_group, _ = Group.objects.get_or_create(name="BD Manager")
        self.bd_user = User.objects.create_user("bd_tester_payload", password="testpass")
        self.bd_user.groups.add(bd_group)

        self.port = Port.objects.create(
            name="Singapore", un_locode="SGSIN", latitude=1.2, longitude=103.8,
            anchorage_latitude=1.25, anchorage_longitude=103.85, geofence_radius_km=30,
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.bd_user)

    def test_opportunity_payload_fields(self):
        vessel = Vessel.objects.create(
            mmsi="123456789",
            imo="9123456",
            name="MARITIME LEADER",
            vessel_type="Crude Oil Tanker",
            grt=50000.0,
            dwt=100000.0,
            flag="PA",
            year_built=2018,
        )
        opp = Opportunity.objects.create(
            vessel=vessel,
            port=self.port,
            zone="24h",
            stage="detected",
            is_inbound=True,
            eta_source="eta_calc",
            lead_reason="Inbound to SGSIN",
        )

        res = self.client.get(f"/api/v1/opportunities/{opp.id}/")
        self.assertEqual(res.status_code, 200)
        data = res.json()

        # Old fields preserved
        self.assertEqual(data["id"], opp.id)
        self.assertEqual(data["vessel"], vessel.id)
        self.assertEqual(data["port"], self.port.id)
        self.assertEqual(data["stage"], "detected")
        self.assertEqual(data["zone"], "24h")
        self.assertIn("score", data)
        self.assertIn("band", data)

        # New fields
        self.assertEqual(data["stage_label"], "Detected")
        self.assertEqual(data["zone_label"], "24 Hour Priority")
        self.assertEqual(data["eta_source"], "eta_calc")
        self.assertTrue(data["is_inbound"])
        self.assertEqual(data["lead_reason"], "Inbound to SGSIN")

        vs = data["vessel_summary"]
        self.assertEqual(vs["id"], vessel.id)
        self.assertEqual(vs["name"], "MARITIME LEADER")
        self.assertEqual(vs["imo"], "9123456")
        self.assertEqual(vs["mmsi"], "123456789")
        self.assertEqual(vs["vessel_type"], "Crude Oil Tanker")
        self.assertEqual(vs["grt"], 50000.0)
        self.assertEqual(vs["dwt"], 100000.0)
        self.assertEqual(vs["flag"], "PA")
        self.assertEqual(vs["year_built"], 2018)

        ps = data["port_summary"]
        self.assertEqual(ps["id"], self.port.id)
        self.assertEqual(ps["name"], "Singapore")
        self.assertEqual(ps["un_locode"], "SGSIN")

    def test_constant_query_count_for_5_vs_25_rows(self):
        # Create 5 opportunities
        for i in range(5):
            v = Vessel.objects.create(mmsi=f"50000{i}", name=f"Vessel {i}")
            Opportunity.objects.create(vessel=v, port=self.port, zone="24h", stage="detected")

        # DRF IsAdminOrBDManager checks Admin & BD Manager groups (2 queries),
        # plus COUNT(*) (1 query) and SELECT ... JOIN (1 query) = 4 queries total.
        with self.assertNumQueries(4):
            res_5 = self.client.get("/api/v1/opportunities/?page_size=25")
            self.assertEqual(res_5.status_code, 200)
            self.assertEqual(res_5.json()["count"], 5)

        # Create 20 more opportunities (25 total)
        for i in range(5, 25):
            v = Vessel.objects.create(mmsi=f"50000{i}", name=f"Vessel {i}")
            Opportunity.objects.create(vessel=v, port=self.port, zone="24h", stage="detected")

        # Query count remains exactly 4 with 25 rows (no N+1 queries)
        with self.assertNumQueries(4):
            res_25 = self.client.get("/api/v1/opportunities/?page_size=25")
            self.assertEqual(res_25.status_code, 200)
            self.assertEqual(res_25.json()["count"], 25)


class OpportunityFilterTests(TestCase):
    def setUp(self):
        from datetime import datetime, timezone, timedelta

        bd_group, _ = Group.objects.get_or_create(name="BD Manager")
        self.bd_user = User.objects.create_user("bd_tester_filter", password="testpass")
        self.bd_user.groups.add(bd_group)

        self.port = Port.objects.create(
            name="Singapore", un_locode="SGSIN", latitude=1.2, longitude=103.8,
            anchorage_latitude=1.25, anchorage_longitude=103.85, geofence_radius_km=30,
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.bd_user)

        now = datetime(2026, 11, 4, 12, 0, 0, tzinfo=timezone.utc)
        self.v1 = Vessel.objects.create(mmsi="211000001", imo="9000001", name="ALPHA STAR")
        self.v2 = Vessel.objects.create(mmsi="211000002", imo="9000002", name="BETA MOON")

        self.opp_open = Opportunity.objects.create(
            vessel=self.v1,
            port=self.port,
            zone="24h",
            stage="detected",
            is_inbound=True,
            eta=now + timedelta(days=1),
        )
        self.opp_closed = Opportunity.objects.create(
            vessel=self.v2,
            port=self.port,
            zone="72h",
            stage="lost",
            is_inbound=False,
            eta=now + timedelta(days=5),
        )

    def test_open_filter(self):
        res_open = self.client.get("/api/v1/opportunities/?open=true")
        self.assertEqual(res_open.json()["count"], 1)
        self.assertEqual(res_open.json()["results"][0]["id"], self.opp_open.id)

        res_closed = self.client.get("/api/v1/opportunities/?open=false")
        self.assertEqual(res_closed.json()["count"], 1)
        self.assertEqual(res_closed.json()["results"][0]["id"], self.opp_closed.id)

    def test_is_inbound_filter(self):
        res_inbound = self.client.get("/api/v1/opportunities/?is_inbound=true")
        self.assertEqual(res_inbound.json()["count"], 1)
        self.assertEqual(res_inbound.json()["results"][0]["id"], self.opp_open.id)

        res_not_inbound = self.client.get("/api/v1/opportunities/?is_inbound=false")
        self.assertEqual(res_not_inbound.json()["count"], 1)
        self.assertEqual(res_not_inbound.json()["results"][0]["id"], self.opp_closed.id)

    def test_q_search_filter(self):
        # Match name
        res_name = self.client.get("/api/v1/opportunities/?q=alpha")
        self.assertEqual(res_name.json()["count"], 1)

        # Match IMO prefix
        res_imo = self.client.get("/api/v1/opportunities/?q=9000002")
        self.assertEqual(res_imo.json()["count"], 1)
        self.assertEqual(res_imo.json()["results"][0]["id"], self.opp_closed.id)

        # Match MMSI prefix
        res_mmsi = self.client.get("/api/v1/opportunities/?q=211000001")
        self.assertEqual(res_mmsi.json()["count"], 1)
        self.assertEqual(res_mmsi.json()["results"][0]["id"], self.opp_open.id)

    def test_eta_filters_and_invalid_date_error(self):
        res_before = self.client.get("/api/v1/opportunities/?eta_before=2026-11-06T00:00:00Z")
        self.assertEqual(res_before.json()["count"], 1)
        self.assertEqual(res_before.json()["results"][0]["id"], self.opp_open.id)

        res_after = self.client.get("/api/v1/opportunities/?eta_after=2026-11-06T00:00:00Z")
        self.assertEqual(res_after.json()["count"], 1)
        self.assertEqual(res_after.json()["results"][0]["id"], self.opp_closed.id)

        res_bad = self.client.get("/api/v1/opportunities/?eta_before=invalid-date")
        self.assertEqual(res_bad.status_code, 400)
        self.assertIn("eta_before", res_bad.json())


class OpportunityNotesAndHistoryTests(TestCase):
    def setUp(self):
        admin_group, _ = Group.objects.get_or_create(name="Admin")
        bd_group, _ = Group.objects.get_or_create(name="BD Manager")

        self.admin_user = User.objects.create_user("admin_opp_notes", password="p", first_name="Alice", last_name="Admin")
        self.admin_user.groups.add(admin_group)

        self.bd_user = User.objects.create_user("bd_opp_notes", password="p", first_name="Bob", last_name="BD")
        self.bd_user.groups.add(bd_group)

        self.plain_user = User.objects.create_user("plain_opp_notes", password="p")

        self.vessel = Vessel.objects.create(mmsi="999888111", name="OCEAN PACIFIC")
        self.port = Port.objects.create(
            name="Singapore", un_locode="SGSIN", latitude=1.2, longitude=103.8,
            anchorage_latitude=1.25, anchorage_longitude=103.85, geofence_radius_km=30,
        )
        self.opp = Opportunity.objects.create(
            vessel=self.vessel, port=self.port, zone="24h", stage="detected"
        )
        self.client = APIClient()

    def test_notes_creation_and_listing(self):
        self.client.force_authenticate(user=self.bd_user)

        # POST note ignores any author in body and uses request.user
        script_text = "Vessel confirmed heading. <script>alert(1)</script>"
        res = self.client.post(
            f"/api/v1/opportunities/{self.opp.id}/notes/",
            {"text": script_text, "author": 999},
            format="json",
        )
        self.assertEqual(res.status_code, 201)
        data = res.json()
        self.assertEqual(data["text"], script_text)
        self.assertEqual(data["author"]["id"], self.bd_user.id)
        self.assertEqual(data["author"]["username"], "bd_opp_notes")
        self.assertEqual(data["author"]["full_name"], "Bob BD")

        # Second note
        self.client.post(
            f"/api/v1/opportunities/{self.opp.id}/notes/",
            {"text": "Second note text"},
            format="json",
        )

        # GET notes: newest first
        res_list = self.client.get(f"/api/v1/opportunities/{self.opp.id}/notes/")
        self.assertEqual(res_list.status_code, 200)
        items = res_list.json()["results"]
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["text"], "Second note text")
        self.assertEqual(items[1]["text"], script_text)

        # Validation: empty text rejected
        res_empty = self.client.post(f"/api/v1/opportunities/{self.opp.id}/notes/", {"text": "   "}, format="json")
        self.assertEqual(res_empty.status_code, 400)

        # Validation: > 2000 chars rejected
        res_long = self.client.post(f"/api/v1/opportunities/{self.opp.id}/notes/", {"text": "A" * 2001}, format="json")
        self.assertEqual(res_long.status_code, 400)

        # Permission: user with no group gets 403
        self.client.force_authenticate(user=self.plain_user)
        res_forbidden = self.client.get(f"/api/v1/opportunities/{self.opp.id}/notes/")
        self.assertEqual(res_forbidden.status_code, 403)

        # Permission: anonymous gets 401/403
        anon = APIClient()
        res_anon = anon.get(f"/api/v1/opportunities/{self.opp.id}/notes/")
        self.assertIn(res_anon.status_code, (401, 403))

    def test_stage_history_recording(self):
        self.client.force_authenticate(user=self.bd_user)

        # 1. Real stage change writes OpportunityStageChange
        res_patch1 = self.client.patch(
            f"/api/v1/opportunities/{self.opp.id}/",
            {"stage": "contacted"},
            format="json",
        )
        self.assertEqual(res_patch1.status_code, 200)
        self.opp.refresh_from_db()
        self.assertEqual(self.opp.stage, "contacted")
        self.assertEqual(self.opp.stage_changes.count(), 1)
        ch1 = self.opp.stage_changes.first()
        self.assertEqual(ch1.from_stage, "detected")
        self.assertEqual(ch1.to_stage, "contacted")
        self.assertEqual(ch1.changed_by, self.bd_user)

        # 2. Same-stage PATCH creates nothing
        res_patch_same = self.client.patch(
            f"/api/v1/opportunities/{self.opp.id}/",
            {"stage": "contacted"},
            format="json",
        )
        self.assertEqual(res_patch_same.status_code, 200)
        self.assertEqual(self.opp.stage_changes.count(), 1)

        # 3. PATCH with valid note creates both
        res_patch_note = self.client.patch(
            f"/api/v1/opportunities/{self.opp.id}/",
            {"stage": "negotiation", "note": "Client requested commercial proposal"},
            format="json",
        )
        self.assertEqual(res_patch_note.status_code, 200)
        self.assertEqual(self.opp.stage_changes.count(), 2)
        self.assertEqual(self.opp.notes.count(), 1)
        self.assertEqual(self.opp.notes.first().text, "Client requested commercial proposal")

        # 4. PATCH with invalid note fails with 400 and saves nothing
        res_patch_invalid_note = self.client.patch(
            f"/api/v1/opportunities/{self.opp.id}/",
            {"stage": "won", "note": "   "},
            format="json",
        )
        self.assertEqual(res_patch_invalid_note.status_code, 400)
        self.opp.refresh_from_db()
        self.assertEqual(self.opp.stage, "negotiation")
        self.assertEqual(self.opp.stage_changes.count(), 2)

        # GET history endpoint
        res_hist = self.client.get(f"/api/v1/opportunities/{self.opp.id}/history/")
        self.assertEqual(res_hist.status_code, 200)
        hist_items = res_hist.json()["results"]
        self.assertEqual(len(hist_items), 2)
        self.assertEqual(hist_items[0]["from_stage"], "contacted")
        self.assertEqual(hist_items[0]["from_stage_label"], "Contacted")
        self.assertEqual(hist_items[0]["to_stage"], "negotiation")
        self.assertEqual(hist_items[0]["to_stage_label"], "Negotiation")
        self.assertEqual(hist_items[0]["changed_by"]["username"], "bd_opp_notes")

    def test_append_only_and_405_on_unsupported_methods(self):
        from .models import OpportunityNote, OpportunityStageChange

        note = OpportunityNote.objects.create(opportunity=self.opp, text="Original text")
        change = OpportunityStageChange.objects.create(
            opportunity=self.opp, from_stage="detected", to_stage="contacted"
        )

        with self.assertRaises(ValueError):
            note.text = "Altered text"
            note.save()

        with self.assertRaises(ValueError):
            change.to_stage = "won"
            change.save()

        self.client.force_authenticate(user=self.admin_user)
        for path in [
            f"/api/v1/opportunities/{self.opp.id}/notes/",
            f"/api/v1/opportunities/{self.opp.id}/history/",
        ]:
            self.assertEqual(self.client.put(path, {}).status_code, 405)
            self.assertEqual(self.client.patch(path, {}).status_code, 405)
            self.assertEqual(self.client.delete(path).status_code, 405)

    def test_csrf_protection_on_notes(self):
        from django.test import Client

        django_client = Client(enforce_csrf_checks=True)
        login_ok = django_client.login(username="bd_opp_notes", password="p")
        self.assertTrue(login_ok)

        # POST without CSRF token fails with 403
        res_no_csrf = django_client.post(
            f"/api/v1/opportunities/{self.opp.id}/notes/",
            {"text": "Attempt without token"},
            content_type="application/json",
        )
        self.assertEqual(res_no_csrf.status_code, 403)

        # GET / to establish CSRF cookie via base template's {% csrf_token %}
        home_page = django_client.get("/")
        csrf_token = home_page.cookies["csrftoken"].value

        # POST with CSRF token succeeds
        res_with_csrf = django_client.post(
            f"/api/v1/opportunities/{self.opp.id}/notes/",
            {"text": "Attempt with token"},
            content_type="application/json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        self.assertEqual(res_with_csrf.status_code, 201)

    def test_won_lost_triggers_related_opportunity_rescoring(self):
        from apps.relationships.models import VesselRelationship
        from apps.companies.models import Company

        company = Company.objects.create(name="Fleet Parent", company_type="owner")
        VesselRelationship.objects.create(vessel=self.vessel, company=company, role="owner", source="test")

        sister_vessel = Vessel.objects.create(mmsi="999888222", name="OCEAN ATLANTIC")
        VesselRelationship.objects.create(vessel=sister_vessel, company=company, role="owner", source="test")

        sister_opp = Opportunity.objects.create(
            vessel=sister_vessel, port=self.port, zone="24h", stage="detected"
        )
        original_score = sister_opp.score

        self.client.force_authenticate(user=self.bd_user)
        # Marking current opportunity as lost applies -20 penalty to sister vessels
        res = self.client.patch(
            f"/api/v1/opportunities/{self.opp.id}/",
            {"stage": "lost"},
            format="json",
        )
        self.assertEqual(res.status_code, 200)

        sister_opp.refresh_from_db()
        # Score is recalculated for sister opportunity
        self.assertNotEqual(sister_opp.score, original_score)

