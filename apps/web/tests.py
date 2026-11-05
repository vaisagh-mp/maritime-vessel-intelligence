"""
apps/web/tests.py

Comprehensive tests for Frontend F0 to F5:
- Authentication & route protection (RoleRequiredMixin: admin & bd_manager vs no-role 403)
- Navigation and role visibility (web_user_role context processor)
- Vessel detail page (/vessels/<id>/): 200 for roles, 404 for missing, data-vessel-id attribute
- Lead detail page (/leads/<id>/): 200 for roles, 404 for missing, data-lead-id attribute
- Shared stage definitions consistency (stages.js matches Django OPPORTUNITY_STAGE_CHOICES & CLOSED_STAGES)
- Lead page safety: no email/mailto, no outreach controls or send triggers
- Static file references & file existence (lead.css, lead.js, lead-logic.js, stages.js, vessel.*, board.*)
- Security rules: no inline scripts/styles, no unsafe DOM sinks
- Centralized fetch() policy
- Node.js test execution for board-logic, vessel-logic, and lead-logic pure functions (36 tests)
- Vessel and Observation API serialization contracts and ordering
"""

import json
import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.staticfiles import finders
from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from apps.common.constants import CLOSED_STAGES, OPPORTUNITY_STAGE_CHOICES
from apps.observations.models import VesselObservation
from apps.observations.serializers import VesselObservationSerializer
from apps.opportunities.models import Opportunity
from apps.ports.models import Port
from apps.vessels.models import Vessel
from apps.vessels.serializers import VesselSerializer

User = get_user_model()


class TestWebFoundations(TestCase):
    """Test suite for Frontend F0-F5 web views, security, access control, and contracts."""

    def setUp(self):
        self.client = Client()

        # Groups from settings
        self.admin_group, _ = Group.objects.get_or_create(name=settings.ROLE_ADMIN)
        self.bd_group, _ = Group.objects.get_or_create(name=settings.ROLE_BD_MANAGER)

        # Users
        self.admin_user = User.objects.create_user(
            username="admin_user",
            password="adminpassword123",
            is_staff=True,
        )
        self.admin_user.groups.add(self.admin_group)

        self.bd_user = User.objects.create_user(
            username="bd_user",
            password="bdpassword123",
            is_staff=False,
        )
        self.bd_user.groups.add(self.bd_group)

        self.plain_user = User.objects.create_user(
            username="plain_user",
            password="plainpassword123",
            is_staff=False,
        )

        # Test vessel
        self.vessel = Vessel.objects.create(
            imo="9811000",
            mmsi="123456789",
            name="EVER GIVEN",
            vessel_type="Container Ship",
            flag="Panama",
            year_built=2018,
            dwt=199692,
            grt=219079,
            length=399.9,
            beam=58.8,
            draught=16.0,
            callsign="H3RC",
            vessel_size_segment="Ultra Large Container Ship",
            ship_id="MT-9811000",
            vessel_type_code="CONT",
            last_dry_dock="2023-05-10",
            last_renewal_survey="2023-05-12",
        )

        # Test port & opportunity
        self.port = Port.objects.create(
            name="Singapore",
            un_locode="SGSIN",
            latitude=1.290270,
            longitude=103.851959,
            anchorage_latitude=1.250000,
            anchorage_longitude=103.850000,
            geofence_radius_km=30.0,
        )
        self.opportunity = Opportunity.objects.create(
            vessel=self.vessel,
            port=self.port,
            stage="detected",
            score=85,
            zone="24h",
            is_inbound=True,
            lead_reason="Vessel inbound with high hull fouling probability.",
        )

    # 1. Anonymous GET / redirects to /login/?next=/
    def test_anonymous_get_home_redirects_to_login(self):
        paths = ["/", f"/vessels/{self.vessel.id}/", f"/leads/{self.opportunity.id}/"]
        for path in paths:
            response = self.client.get(path)
            self.assertEqual(response.status_code, 302, f"Failed for {path}")
            self.assertIn(f"/login/?next={path}", response.headers["Location"])

    # 2. GET /login/ returns 200 and sets CSRF cookie; wrong password returns 200 with role="alert"
    def test_login_view_and_csrf_and_invalid_credentials(self):
        response = self.client.get("/login/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="csrfmiddlewaretoken"')
        self.assertIn("csrftoken", response.cookies)

        post_response = self.client.post(
            "/login/",
            {"username": "admin_user", "password": "wrongpassword"},
        )
        self.assertEqual(post_response.status_code, 200)
        content = post_response.content.decode("utf-8")
        self.assertIn('role="alert"', content)
        self.assertIn("Please enter a correct username and password", content)

    # 3. Access control: Admin & BD Manager get 200, user with no role gets 403 friendly page
    def test_role_access_and_no_access_page(self):
        paths = ["/", f"/vessels/{self.vessel.id}/", f"/leads/{self.opportunity.id}/"]

        # User with no role gets 403 on all pages
        self.client.login(username="plain_user", password="plainpassword123")
        for path in paths:
            res_no_role = self.client.get(path)
            self.assertEqual(res_no_role.status_code, 403, f"Expected 403 on {path}")
            self.assertContains(res_no_role, "Access Denied", status_code=403)
            self.assertContains(res_no_role, "plain_user", status_code=403)
            self.assertContains(res_no_role, "This account has no role assigned", status_code=403)
            self.assertContains(res_no_role, 'action="/logout/"', status_code=403)
        self.client.logout()

        # Admin gets 200 on all pages
        self.client.login(username="admin_user", password="adminpassword123")
        for path in paths:
            res_admin = self.client.get(path)
            self.assertEqual(res_admin.status_code, 200, f"Expected 200 for admin on {path}")
        self.client.logout()

        # BD Manager gets 200 on all pages
        self.client.login(username="bd_user", password="bdpassword123")
        for path in paths:
            res_bd = self.client.get(path)
            self.assertEqual(res_bd.status_code, 200, f"Expected 200 for BD Manager on {path}")
        self.client.logout()

    # 4. Role label and active-link markup in top bar
    def test_role_label_and_active_navigation_markup(self):
        # Admin role badge
        self.client.login(username="admin_user", password="adminpassword123")
        res_admin = self.client.get("/")
        self.assertEqual(res_admin.status_code, 200)
        self.assertContains(res_admin, '<span class="user-role-pill">Role: Admin</span>')
        self.assertNotContains(res_admin, '<button class="user-role-pill"')
        self.assertNotContains(res_admin, '<a class="user-role-pill"')
        self.assertContains(res_admin, 'aria-current="page"')
        self.client.logout()

        # BD Manager role badge
        self.client.login(username="bd_user", password="bdpassword123")
        res_bd = self.client.get("/")
        self.assertEqual(res_bd.status_code, 200)
        self.assertContains(res_bd, '<span class="user-role-pill">Role: BD Manager</span>')
        self.assertNotContains(res_bd, '<button class="user-role-pill"')
        self.assertNotContains(res_bd, '<a class="user-role-pill"')
        self.assertContains(res_bd, 'aria-current="page"')
        self.client.logout()

    # 5. Vessel detail view: 200 with data-vessel-id, 404 for unknown ID, placeholder template gone
    def test_vessel_detail_view(self):
        self.client.login(username="bd_user", password="bdpassword123")

        # Real vessel page
        res_vessel = self.client.get(f"/vessels/{self.vessel.id}/")
        self.assertEqual(res_vessel.status_code, 200)
        self.assertContains(res_vessel, f'data-vessel-id="{self.vessel.id}"')
        self.assertContains(res_vessel, "EVER GIVEN")
        self.assertContains(res_vessel, "vessel.js")
        self.assertContains(res_vessel, "vessel-logic.js")
        self.assertContains(res_vessel, "vessel.css")

        # Unknown vessel returns 404
        res_404 = self.client.get("/vessels/999999/")
        self.assertEqual(res_404.status_code, 404)

        # Old placeholder template must be gone
        templates_dir = os.path.join(settings.BASE_DIR, "apps", "web", "templates", "web")
        old_template_path = os.path.join(templates_dir, "vessel_placeholder.html")
        self.assertFalse(os.path.exists(old_template_path), "vessel_placeholder.html should be removed")

        self.client.logout()

    # 6. Lead detail view: 200 with data-lead-id, 404 for unknown ID, placeholder template gone
    def test_lead_detail_view(self):
        self.client.login(username="bd_user", password="bdpassword123")

        # Real lead page
        res_lead = self.client.get(f"/leads/{self.opportunity.id}/")
        self.assertEqual(res_lead.status_code, 200)
        self.assertContains(res_lead, f'data-lead-id="{self.opportunity.id}"')
        self.assertContains(res_lead, "EVER GIVEN")
        self.assertContains(res_lead, "lead.js")
        self.assertContains(res_lead, "lead-logic.js")
        self.assertContains(res_lead, "stages.js")
        self.assertContains(res_lead, "lead.css")

        # Unknown lead returns 404
        res_404 = self.client.get("/leads/999999/")
        self.assertEqual(res_404.status_code, 404)

        # Placeholder template must be deleted
        templates_dir = os.path.join(settings.BASE_DIR, "apps", "web", "templates", "web")
        old_template_path = os.path.join(templates_dir, "lead_placeholder.html")
        self.assertFalse(os.path.exists(old_template_path), "lead_placeholder.html should be removed")

        self.client.logout()

    # 7. Shared stage definitions consistency: stages.js matches Django constants
    def test_stages_js_consistency_with_django_constants(self):
        stages_path = os.path.join(
            settings.BASE_DIR, "apps", "web", "static", "web", "js", "stages.js"
        )
        self.assertTrue(os.path.exists(stages_path), "stages.js does not exist")

        with open(stages_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Extract values and labels from STAGES array
        stage_matches = re.findall(
            r'\{\s*value:\s*"([^"]+)",\s*label:\s*"([^"]+)"\s*\}', content
        )
        js_stages = [(m[0], m[1]) for m in stage_matches]

        # Must match OPPORTUNITY_STAGE_CHOICES exactly in order and text
        self.assertEqual(
            js_stages,
            list(OPPORTUNITY_STAGE_CHOICES),
            "stages.js STAGES does not match Django OPPORTUNITY_STAGE_CHOICES",
        )

        # Extract CLOSED_STAGE_VALUES
        closed_match = re.search(r"export const CLOSED_STAGE_VALUES\s*=\s*\[([^\]]+)\]", content)
        self.assertIsNotNone(closed_match, "CLOSED_STAGE_VALUES not found in stages.js")
        raw_values = [v.strip().strip('"').strip("'") for v in closed_match.group(1).split(",")]
        js_closed_set = {v for v in raw_values if v}

        self.assertEqual(
            js_closed_set,
            set(CLOSED_STAGES),
            "stages.js CLOSED_STAGE_VALUES does not match Django CLOSED_STAGES",
        )

    # 8. Lead page safety: no email/mailto, no outreach controls or send triggers
    def test_lead_page_safety_and_no_outreach_controls(self):
        templates_dir = os.path.join(settings.BASE_DIR, "apps", "web", "templates", "web")
        lead_html_path = os.path.join(templates_dir, "lead.html")
        with open(lead_html_path, "r", encoding="utf-8") as f:
            html_content = f.read().lower()

        js_dir = os.path.join(settings.BASE_DIR, "apps", "web", "static", "web", "js")
        lead_js_path = os.path.join(js_dir, "lead.js")
        with open(lead_js_path, "r", encoding="utf-8") as f:
            js_content = f.read().lower()

        # Neither HTML nor JS should contain mailto:
        self.assertNotIn("mailto:", html_content, "mailto: found in lead.html")
        self.assertNotIn("mailto:", js_content, "mailto: found in lead.js")

        # No outreach / send buttons or triggers
        self.assertNotIn(">send<", html_content, "'send' button text found in lead.html")
        self.assertNotIn("send email", html_content, "'send email' text found in lead.html")
        self.assertNotIn("send message", html_content, "'send message' text found in lead.html")
        self.assertNotIn("outreach", html_content, "outreach control found in lead.html")

    # 9. GET /logout/ is not allowed (405); POST /logout/ logs out and redirects to /login/
    def test_logout_behavior(self):
        self.client.login(username="bd_user", password="bdpassword123")

        get_response = self.client.get("/logout/")
        self.assertEqual(get_response.status_code, 405)

        post_response = self.client.post("/logout/")
        self.assertEqual(post_response.status_code, 302)
        self.assertEqual(post_response.headers["Location"], "/login/")

        home_after_logout = self.client.get("/")
        self.assertEqual(home_after_logout.status_code, 302)

    # 10. Admin nav link present for staff user, absent for non-staff
    def test_admin_nav_link_visibility(self):
        self.client.login(username="admin_user", password="adminpassword123")
        res_staff = self.client.get("/")
        self.assertContains(res_staff, '<a href="/admin/" class="nav-link">Django admin</a>')
        self.client.logout()

        self.client.login(username="bd_user", password="bdpassword123")
        res_non_staff = self.client.get("/")
        self.assertNotContains(res_non_staff, "Django admin")
        self.client.logout()

    # 11. Home page, Vessel page, and Lead page reference static files and finders find them on disk
    def test_static_files_referenced_and_exist(self):
        self.client.login(username="admin_user", password="adminpassword123")
        res_home = self.client.get("/")
        content_home = res_home.content.decode("utf-8")

        res_vessel = self.client.get(f"/vessels/{self.vessel.id}/")
        content_vessel = res_vessel.content.decode("utf-8")

        res_lead = self.client.get(f"/leads/{self.opportunity.id}/")
        content_lead = res_lead.content.decode("utf-8")

        all_rendered_content = content_home + content_vessel + content_lead

        expected_statics = [
            "web/css/tokens.css",
            "web/css/base.css",
            "web/css/components.css",
            "web/css/board.css",
            "web/js/stages.js",
            "web/js/board-logic.js",
            "web/js/board.js",
            "web/css/vessel.css",
            "web/js/vessel-logic.js",
            "web/js/vessel.js",
            "web/css/lead.css",
            "web/js/lead-logic.js",
            "web/js/lead.js",
        ]

        for rel_path in expected_statics:
            self.assertTrue(
                rel_path in all_rendered_content,
                f"Static reference '{rel_path}' missing from templates",
            )
            found_path = finders.find(rel_path)
            self.assertIsNotNone(found_path, f"Static file '{rel_path}' not found by finders")
            self.assertTrue(os.path.exists(found_path), f"File on disk '{found_path}' does not exist")

        self.client.logout()

    # 12. No template contains inline <script> body or style= attribute
    def test_no_inline_scripts_or_styles_in_templates(self):
        templates_dir = os.path.join(settings.BASE_DIR, "apps", "web", "templates", "web")
        template_files = [f for f in os.listdir(templates_dir) if f.endswith(".html")]
        self.assertTrue(len(template_files) > 0)

        for filename in template_files:
            filepath = os.path.join(templates_dir, filename)
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()

            self.assertNotIn("style=", content, f"Inline style= found in {filename}")

            lower = content.lower()
            start = 0
            while True:
                idx = lower.find("<script", start)
                if idx == -1:
                    break
                end = lower.find(">", idx)
                script_tag = lower[idx : end + 1]
                self.assertIn("src=", script_tag, f"Inline script tag without src= found in {filename}")
                start = end + 1

    # 13. No JavaScript file in static/web/js/ contains innerHTML, outerHTML, document.write, or eval(
    def test_no_unsafe_dom_sinks_in_js(self):
        js_dir = os.path.join(settings.BASE_DIR, "apps", "web", "static", "web", "js")
        js_files = [f for f in os.listdir(js_dir) if f.endswith(".js") or f.endswith(".mjs")]
        self.assertTrue(len(js_files) > 0)

        forbidden_sinks = ["innerHTML", "outerHTML", "document.write", "eval("]

        for filename in js_files:
            filepath = os.path.join(js_dir, filename)
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()

            for sink in forbidden_sinks:
                self.assertNotIn(sink, content, f"Forbidden sink '{sink}' found in {filename}")

    # 14. api.js is the only JS file containing fetch(
    def test_only_api_js_contains_fetch(self):
        js_dir = os.path.join(settings.BASE_DIR, "apps", "web", "static", "web", "js")
        js_files = [f for f in os.listdir(js_dir) if f.endswith(".js") or f.endswith(".mjs")]
        self.assertTrue(len(js_files) > 0)

        for filename in js_files:
            filepath = os.path.join(js_dir, filename)
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()

            if filename == "api.js":
                self.assertIn("fetch(", content, "api.js must contain fetch()")
            else:
                self.assertNotIn("fetch(", content, f"Disallowed fetch() found in {filename}")

    # 15. Run JavaScript pure functions unit tests using node --test (board-logic, vessel-logic, lead-logic)
    def test_node_unit_tests(self):
        node_bin = shutil.which("node")
        if not node_bin:
            self.skipTest("Node.js is not available on PATH.")

        tests_dir = os.path.join(
            settings.BASE_DIR,
            "apps",
            "web",
            "static",
            "web",
            "js",
            "tests",
        )
        board_test = os.path.join(tests_dir, "board-logic.test.mjs")
        vessel_test = os.path.join(tests_dir, "vessel-logic.test.mjs")
        lead_test = os.path.join(tests_dir, "lead-logic.test.mjs")
        ui_test = os.path.join(tests_dir, "ui.test.mjs")
        undeclared_test = os.path.join(tests_dir, "undeclared.test.mjs")

        self.assertTrue(os.path.exists(board_test), f"Test file {board_test} does not exist.")
        self.assertTrue(os.path.exists(vessel_test), f"Test file {vessel_test} does not exist.")
        self.assertTrue(os.path.exists(lead_test), f"Test file {lead_test} does not exist.")
        self.assertTrue(os.path.exists(ui_test), f"Test file {ui_test} does not exist.")
        self.assertTrue(os.path.exists(undeclared_test), f"Test file {undeclared_test} does not exist.")

        result = subprocess.run(
            [node_bin, "--test", board_test, vessel_test, lead_test, ui_test, undeclared_test],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            self.fail(f"Node tests failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}")
        self.assertIn("pass 56", result.stdout)

    # 16. Vessel and Observation API contracts: serializer fields read-only and observations ordered newest first
    def test_vessel_and_observation_api_contracts(self):
        # Vessel serializer fields
        v_serializer = VesselSerializer(self.vessel)
        v_data = v_serializer.data

        expected_vessel_fields = [
            "id", "imo", "mmsi", "name", "vessel_type", "dwt", "grt", "flag",
            "year_built", "length", "beam", "draught", "callsign", "ship_id",
            "vessel_type_code", "vessel_size_segment", "last_dry_dock",
            "last_renewal_survey", "created_at", "updated_at",
        ]
        for field in expected_vessel_fields:
            self.assertIn(field, v_data, f"Vessel field '{field}' missing from serializer data")
            self.assertIn(field, VesselSerializer.Meta.read_only_fields)

        # Create two observations with distinct timestamps
        obs_old = VesselObservation.objects.create(
            vessel=self.vessel,
            timestamp=datetime(2026, 11, 4, 10, 0, tzinfo=timezone.utc),
            latitude=1.20000,
            longitude=103.80000,
            speed=12.5,
            course=90.0,
            source="test:kpler",
            navigational_status=0,
            port_area="inbound",
            destination="SINGAPORE",
            next_port_unlocode="SGSIN",
        )
        obs_new = VesselObservation.objects.create(
            vessel=self.vessel,
            timestamp=datetime(2026, 11, 5, 8, 0, tzinfo=timezone.utc),
            latitude=1.25000,
            longitude=103.85000,
            speed=5.0,
            course=45.0,
            source="test:kpler",
            navigational_status=1,
            port_area="anchorage",
            destination="SINGAPORE",
            next_port_unlocode="SGSIN",
        )

        obs_serializer = VesselObservationSerializer(obs_new)
        obs_data = obs_serializer.data

        expected_obs_fields = [
            "id", "vessel", "timestamp", "latitude", "longitude", "speed", "course",
            "source", "navigational_status", "destination", "next_port_unlocode",
            "eta_calc", "eta_updated", "last_port", "last_port_unlocode",
            "last_port_time", "current_port", "port_area",
        ]
        for field in expected_obs_fields:
            self.assertIn(field, obs_data, f"Observation field '{field}' missing from serializer data")
            self.assertIn(field, VesselObservationSerializer.Meta.read_only_fields)

        # Query GET /api/v1/vessels/{id}/observations/ via BD client
        self.client.login(username="bd_user", password="bdpassword123")
        res_obs = self.client.get(f"/api/v1/vessels/{self.vessel.id}/observations/")
        self.assertEqual(res_obs.status_code, 200)

        results = res_obs.data.get("results", res_obs.data)
        self.assertGreaterEqual(len(results), 2)
        # Newest observation (obs_new) must come first
        self.assertEqual(results[0]["id"], obs_new.id)
        self.assertEqual(results[1]["id"], obs_old.id)
        self.client.logout()

    # 17. Page header is the immediate first child element of <main> on Lead and Vessel pages
    def test_page_header_is_first_child_of_main(self):
        self.client.login(username="admin_user", password="adminpassword123")

        # Test lead page
        res_lead = self.client.get(f"/leads/{self.opportunity.id}/")
        self.assertEqual(res_lead.status_code, 200)
        content_lead = res_lead.content.decode("utf-8")
        main_match_lead = re.search(r"<main[^>]*>\s*(<!--.*?-->\s*)*<header\s+id=[\"']page-header[\"']", content_lead)
        self.assertIsNotNone(main_match_lead, "#page-header must be the first child of <main> on lead page")

        # Test vessel page
        res_vessel = self.client.get(f"/vessels/{self.vessel.id}/")
        self.assertEqual(res_vessel.status_code, 200)
        content_vessel = res_vessel.content.decode("utf-8")
        main_match_vessel = re.search(r"<main[^>]*>\s*(<!--.*?-->\s*)*<header\s+id=[\"']page-header[\"']", content_vessel)
        self.assertIsNotNone(main_match_vessel, "#page-header must be the first child of <main> on vessel page")

        self.client.logout()

    # 18. CSS hygiene: No hardcoded colors outside tokens.css; no !important anywhere in any CSS file
    def test_css_hygiene(self):
        css_dir = os.path.join(settings.BASE_DIR, "apps", "web", "static", "web", "css")
        css_files = [f for f in os.listdir(css_dir) if f.endswith(".css")]
        self.assertTrue(len(css_files) > 0)

        color_pattern = re.compile(r"(#[0-9a-fA-F]{3,8}\b|rgb\s*\(|rgba\s*\(|hsl\s*\(|hsla\s*\()")

        for filename in css_files:
            filepath = os.path.join(css_dir, filename)
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()

            # Rule 1: No !important anywhere in any CSS file
            self.assertNotIn("!important", content, f"!important found in {filename}")

            # Rule 2: No hex, rgb, rgba, hsl, hsla in any CSS file other than tokens.css
            if filename != "tokens.css":
                match = color_pattern.search(content)
                self.assertIsNone(
                    match,
                    f"Hardcoded color '{match.group(0) if match else ''}' found in {filename}",
                )

    # 19. Stale module guard: meta static-version exists and entry scripts are versioned with ?v=\d+
    def test_static_version_meta_and_entry_scripts(self):
        self.client.login(username="admin_user", password="adminpassword123")

        pages = [
            ("/", r"board\.js\?v=\d+"),
            (f"/vessels/{self.vessel.id}/", r"vessel\.js\?v=\d+"),
            (f"/leads/{self.opportunity.id}/", r"lead\.js\?v=\d+"),
        ]

        for path, script_pattern in pages:
            res = self.client.get(path)
            self.assertEqual(res.status_code, 200, f"Failed for {path}")
            html = res.content.decode("utf-8")

            # Check meta static-version tag
            meta_match = re.search(r'<meta\s+name=["\']static-version["\']\s+content=["\'](\d+)["\']', html)
            self.assertIsNotNone(meta_match, f"<meta name='static-version'> missing or non-numeric on {path}")

            # Check entry script URL contains ?v=\d+
            script_match = re.search(script_pattern, html)
            self.assertIsNotNone(script_match, f"Entry script matching '{script_pattern}' not found on {path}")

        self.client.logout()

    # 20. Controller hygiene: board.js, vessel.js, and lead.js use onReady instead of raw DOMContentLoaded listener
    def test_controllers_use_on_ready_hygiene(self):
        js_dir = os.path.join(settings.BASE_DIR, "apps", "web", "static", "web", "js")
        controllers = ["board.js", "vessel.js", "lead.js"]

        for filename in controllers:
            filepath = os.path.join(js_dir, filename)
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()

            self.assertIn("onReady(", content, f"{filename} must use onReady(...) for safe lifecycle execution")
            self.assertNotIn(
                'document.addEventListener("DOMContentLoaded"',
                content,
                f"{filename} must not attach raw DOMContentLoaded listener directly; use onReady instead",
            )

    # 21. Reset filters button with stable id and live status element
    def test_reset_filters_button_and_status_element(self):
        self.client.login(username="admin_user", password="adminpassword123")
        res = self.client.get("/")
        self.assertEqual(res.status_code, 200)
        html = res.content.decode("utf-8")

        self.assertIn('id="reset-filters"', html, "Home page must contain button with id='reset-filters'")
        self.assertIn('id="filter-status"', html, "Home page must contain status element id='filter-status'")
        self.assertIn('aria-live="polite"', html, "Status element must specify aria-live='polite'")
        self.client.logout()

    # 22. Production static files: collectstatic with STATIC_HASHING produces hashed imports and manifest
    def test_collectstatic_hashed_imports(self):
        with tempfile.TemporaryDirectory() as tmp_static:
            with override_settings(
                STATIC_ROOT=tmp_static,
                STATIC_HASHING=True,
                STORAGES={
                    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
                    "staticfiles": {"BACKEND": "apps.web.storage.AggregatedManifestStaticFilesStorage"},
                },
            ):
                call_command("collectstatic", interactive=False, verbosity=0)

                manifest_path = os.path.join(tmp_static, "staticfiles.json")
                self.assertTrue(os.path.exists(manifest_path), "staticfiles.json manifest was not written")

                with open(manifest_path, "r", encoding="utf-8") as f:
                    manifest = json.load(f)

                paths = manifest.get("paths", {})
                vessel_hashed = paths.get("web/js/vessel.js")
                self.assertIsNotNone(vessel_hashed, "web/js/vessel.js not present in staticfiles manifest")

                collected_vessel_path = os.path.join(tmp_static, vessel_hashed)
                self.assertTrue(os.path.exists(collected_vessel_path), f"Collected file {collected_vessel_path} does not exist")

                with open(collected_vessel_path, "r", encoding="utf-8") as vf:
                    vessel_content = vf.read()

                # Assert that imports in vessel.js were rewritten to hashed filenames
                api_hashed = paths.get("web/js/api.js")
                ui_hashed = paths.get("web/js/ui.js")
                logic_hashed = paths.get("web/js/vessel-logic.js")

                self.assertIsNotNone(api_hashed, "web/js/api.js missing from manifest")
                self.assertIsNotNone(ui_hashed, "web/js/ui.js missing from manifest")
                self.assertIsNotNone(logic_hashed, "web/js/vessel-logic.js missing from manifest")

                api_base = os.path.basename(api_hashed)
                ui_base = os.path.basename(ui_hashed)
                logic_base = os.path.basename(logic_hashed)

                self.assertIn(api_base, vessel_content, f"Hashed import for {api_base} not found in collected vessel.js")
                self.assertIn(ui_base, vessel_content, f"Hashed import for {ui_base} not found in collected vessel.js")
                self.assertIn(logic_base, vessel_content, f"Hashed import for {logic_base} not found in collected vessel.js")

                # Assert target hashed files physically exist in STATIC_ROOT
                self.assertTrue(os.path.exists(os.path.join(tmp_static, api_hashed)))
                self.assertTrue(os.path.exists(os.path.join(tmp_static, ui_hashed)))
                self.assertTrue(os.path.exists(os.path.join(tmp_static, logic_hashed)))
