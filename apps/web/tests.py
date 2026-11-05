"""
apps/web/tests.py

Comprehensive tests for Frontend F0 to F4:
- Authentication & route protection (RoleRequiredMixin: admin & bd_manager vs no-role 403)
- Navigation and role visibility (web_user_role context processor)
- Vessel detail page (/vessels/<id>/): 200 for roles, 404 for missing, data-vessel-id attribute
- Lead placeholder page (/leads/<id>/)
- Static file references & file existence (vessel.css, vessel.js, vessel-logic.js)
- Security rules: no inline scripts/styles, no unsafe DOM sinks
- Centralized fetch() policy
- Node.js test execution for board-logic and vessel-logic pure functions
- Vessel and Observation API serialization contracts and ordering
"""

import os
import shutil
import subprocess
from datetime import datetime, timezone
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.staticfiles import finders
from django.test import Client, TestCase
from django.urls import reverse

from apps.observations.models import VesselObservation
from apps.observations.serializers import VesselObservationSerializer
from apps.vessels.models import Vessel
from apps.vessels.serializers import VesselSerializer

User = get_user_model()


class TestWebFoundations(TestCase):
    """Test suite for Frontend F0-F4 web views, security, access control, and contracts."""

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

    # 1. Anonymous GET / redirects to /login/?next=/
    def test_anonymous_get_home_redirects_to_login(self):
        paths = ["/", f"/vessels/{self.vessel.id}/", "/leads/1/"]
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
        paths = ["/", f"/vessels/{self.vessel.id}/", "/leads/1/"]

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
        self.assertContains(res_admin, '<span class="user-role">Admin</span>')
        self.assertContains(res_admin, 'aria-current="page"')
        self.client.logout()

        # BD Manager role badge
        self.client.login(username="bd_user", password="bdpassword123")
        res_bd = self.client.get("/")
        self.assertEqual(res_bd.status_code, 200)
        self.assertContains(res_bd, '<span class="user-role">BD Manager</span>')
        self.assertContains(res_bd, 'aria-current="page"')
        self.client.logout()

    # 5. Vessel detail view: 200 with data-vessel-id, 404 for unknown ID, placeholder template gone
    def test_vessel_detail_view_and_placeholders(self):
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

        # Lead placeholder still works
        res_lead = self.client.get("/leads/42/")
        self.assertEqual(res_lead.status_code, 200)
        self.assertContains(res_lead, "This page arrives in phase F5")

        self.client.logout()

    # 6. GET /logout/ is not allowed (405); POST /logout/ logs out and redirects to /login/
    def test_logout_behavior(self):
        self.client.login(username="bd_user", password="bdpassword123")

        get_response = self.client.get("/logout/")
        self.assertEqual(get_response.status_code, 405)

        post_response = self.client.post("/logout/")
        self.assertEqual(post_response.status_code, 302)
        self.assertEqual(post_response.headers["Location"], "/login/")

        home_after_logout = self.client.get("/")
        self.assertEqual(home_after_logout.status_code, 302)

    # 7. Admin nav link present for staff user, absent for non-staff
    def test_admin_nav_link_visibility(self):
        self.client.login(username="admin_user", password="adminpassword123")
        res_staff = self.client.get("/")
        self.assertContains(res_staff, '<a href="/admin/" class="nav-link">Admin</a>')
        self.client.logout()

        self.client.login(username="bd_user", password="bdpassword123")
        res_non_staff = self.client.get("/")
        self.assertNotContains(res_non_staff, '<a href="/admin/" class="nav-link">Admin</a>')
        self.client.logout()

    # 8. Home page and Vessel detail page reference static files and finders find them on disk
    def test_static_files_referenced_and_exist(self):
        self.client.login(username="admin_user", password="adminpassword123")
        res_home = self.client.get("/")
        content_home = res_home.content.decode("utf-8")

        res_vessel = self.client.get(f"/vessels/{self.vessel.id}/")
        content_vessel = res_vessel.content.decode("utf-8")

        expected_statics = [
            "web/css/tokens.css",
            "web/css/base.css",
            "web/css/components.css",
            "web/css/board.css",
            "web/js/board-logic.js",
            "web/js/board.js",
            "web/css/vessel.css",
            "web/js/vessel-logic.js",
            "web/js/vessel.js",
        ]

        for rel_path in expected_statics:
            self.assertTrue(
                rel_path in content_home or rel_path in content_vessel,
                f"Static reference '{rel_path}' missing from templates"
            )
            found_path = finders.find(rel_path)
            self.assertIsNotNone(found_path, f"Static file '{rel_path}' not found by finders")
            self.assertTrue(os.path.exists(found_path), f"File on disk '{found_path}' does not exist")

        self.client.logout()

    # 9. No template contains inline <script> body or style= attribute
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
                script_tag = lower[idx:end + 1]
                self.assertIn("src=", script_tag, f"Inline script tag without src= found in {filename}")
                start = end + 1

    # 10. No JavaScript file in static/web/js/ contains innerHTML, outerHTML, document.write, or eval(
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

    # 11. api.js is the only JS file containing fetch(
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

    # 12. Run JavaScript pure functions unit tests using node --test (both board-logic and vessel-logic)
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

        self.assertTrue(os.path.exists(board_test), f"Test file {board_test} does not exist.")
        self.assertTrue(os.path.exists(vessel_test), f"Test file {vessel_test} does not exist.")

        result = subprocess.run(
            [node_bin, "--test", board_test, vessel_test],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            self.fail(f"Node tests failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}")
        self.assertIn("pass 26", result.stdout)

    # 13. Vessel and Observation API contracts: serializer fields read-only and observations ordered newest first
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
