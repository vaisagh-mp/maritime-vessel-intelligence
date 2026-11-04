"""
apps/web/tests.py

Comprehensive tests for Frontend F0, F1, F2 & F3:
- Authentication & route protection (RoleRequiredMixin: admin & bd_manager vs no-role 403)
- Navigation and role visibility (web_user_role context processor)
- Static file references & file existence
- Security rules: no inline scripts/styles, no unsafe DOM sinks
- Centralized fetch() policy
- Placeholders for vessels and leads
- Node.js test execution for board-logic pure functions
"""

import os
import shutil
import subprocess
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.staticfiles import finders
from django.test import Client, TestCase
from django.urls import reverse

User = get_user_model()


class TestWebFoundations(TestCase):
    """Test suite for Frontend F0-F3 web views, security, and access control."""

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

    # 1. Anonymous GET / redirects to /login/?next=/
    def test_anonymous_get_home_redirects_to_login(self):
        for path in ["/", "/vessels/1/", "/leads/1/"]:
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
        paths = ["/", "/vessels/1/", "/leads/1/"]

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

    # 5. Placeholders content check
    def test_placeholder_pages_content(self):
        self.client.login(username="bd_user", password="bdpassword123")

        res_vessel = self.client.get("/vessels/42/")
        self.assertEqual(res_vessel.status_code, 200)
        self.assertContains(res_vessel, "This page arrives in phase F4")
        self.assertContains(res_vessel, 'href="/"')

        res_lead = self.client.get("/leads/42/")
        self.assertEqual(res_lead.status_code, 200)
        self.assertContains(res_lead, "This page arrives in phase F5")
        self.assertContains(res_lead, 'href="/"')

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

    # 8. Home page references static files and finders find them on disk
    def test_static_files_referenced_and_exist(self):
        self.client.login(username="admin_user", password="adminpassword123")
        response = self.client.get("/")
        content = response.content.decode("utf-8")

        expected_statics = [
            "web/css/tokens.css",
            "web/css/base.css",
            "web/css/components.css",
            "web/css/board.css",
            "web/js/board-logic.js",
            "web/js/board.js",
        ]

        for rel_path in expected_statics:
            self.assertIn(rel_path, content, f"Static reference '{rel_path}' missing from home page")
            found_path = finders.find(rel_path)
            self.assertIsNotNone(found_path, f"Static file '{rel_path}' not found by finders")
            self.assertTrue(os.path.exists(found_path), f"File on disk '{found_path}' does not exist")

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

    # 12. Run JavaScript pure functions unit tests using node --test
    def test_node_board_logic_tests(self):
        node_bin = shutil.which("node")
        if not node_bin:
            self.skipTest("Node.js is not available on PATH.")

        test_file = os.path.join(
            settings.BASE_DIR,
            "apps",
            "web",
            "static",
            "web",
            "js",
            "tests",
            "board-logic.test.mjs",
        )
        self.assertTrue(os.path.exists(test_file), f"Test file {test_file} does not exist.")

        result = subprocess.run(
            [node_bin, "--test", test_file],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            self.fail(f"Node board-logic tests failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}")
        self.assertIn("pass 10", result.stdout)
