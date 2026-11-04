"""
apps/web/tests.py

Comprehensive tests for Frontend F0 foundations:
- Authentication & route protection
- Navigation and role visibility
- Static file references & file existence
- Security rules: no inline scripts/styles, no unsafe DOM sinks
- Centralized fetch() policy
- API routing preservation
"""

import os
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.staticfiles import finders
from django.test import Client, TestCase
from django.urls import reverse

User = get_user_model()


class TestWebFoundations(TestCase):
    """Test suite for Frontend F0 foundations."""

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
        response = self.client.get("/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login/?next=/", response.headers["Location"])

    # 2. GET /login/ returns 200 and sets CSRF cookie; wrong password returns 200 with role="alert"
    def test_login_view_and_csrf_and_invalid_credentials(self):
        # GET /login/
        response = self.client.get("/login/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="csrfmiddlewaretoken"')
        self.assertIn("csrftoken", response.cookies)

        # Wrong password POST
        post_response = self.client.post(
            "/login/",
            {"username": "admin_user", "password": "wrongpassword"},
        )
        self.assertEqual(post_response.status_code, 200)
        content = post_response.content.decode("utf-8")
        self.assertIn('role="alert"', content)
        self.assertIn("Please enter a correct username and password", content)

    # 3. Correct login redirects to /; GET / returns 200 for Admin and BD Manager
    def test_successful_login_and_home_access(self):
        # Login Admin
        login_response = self.client.post(
            "/login/",
            {"username": "admin_user", "password": "adminpassword123"},
        )
        self.assertEqual(login_response.status_code, 302)
        self.assertEqual(login_response.headers["Location"], "/")

        home_response = self.client.get("/")
        self.assertEqual(home_response.status_code, 200)
        self.assertContains(home_response, "Lead board")
        self.assertContains(home_response, "The lead board arrives in phase F3.")
        self.client.logout()

        # Login BD Manager
        self.client.login(username="bd_user", password="bdpassword123")
        home_bd = self.client.get("/")
        self.assertEqual(home_bd.status_code, 200)
        self.assertContains(home_bd, "Lead board")
        self.client.logout()

    # 4. GET /logout/ is not allowed (405); POST /logout/ logs out and redirects to /login/
    def test_logout_behavior(self):
        self.client.login(username="bd_user", password="bdpassword123")

        # GET /logout/ must return 405 Method Not Allowed in Django 5
        get_response = self.client.get("/logout/")
        self.assertEqual(get_response.status_code, 405)

        # POST /logout/ logs out and redirects to /login/
        post_response = self.client.post("/logout/")
        self.assertEqual(post_response.status_code, 302)
        self.assertEqual(post_response.headers["Location"], "/login/")

        # Verify session is logged out (subsequent GET / redirects)
        home_after_logout = self.client.get("/")
        self.assertEqual(home_after_logout.status_code, 302)

    # 5. Admin nav link present for staff user, absent for non-staff
    def test_admin_nav_link_visibility(self):
        # Staff user
        self.client.login(username="admin_user", password="adminpassword123")
        res_staff = self.client.get("/")
        self.assertContains(res_staff, '<a href="/admin/" class="nav-link">Admin</a>')
        self.client.logout()

        # Non-staff user
        self.client.login(username="bd_user", password="bdpassword123")
        res_non_staff = self.client.get("/")
        self.assertNotContains(res_non_staff, '<a href="/admin/" class="nav-link">Admin</a>')
        self.client.logout()

    # 6. Home page references static files and finders find them on disk
    def test_static_files_referenced_and_exist(self):
        self.client.login(username="admin_user", password="adminpassword123")
        response = self.client.get("/")
        content = response.content.decode("utf-8")

        expected_statics = [
            "web/css/tokens.css",
            "web/css/base.css",
            "web/css/components.css",
            "web/js/home.js",
        ]

        for rel_path in expected_statics:
            self.assertIn(rel_path, content, f"Static reference '{rel_path}' missing from home page")
            found_path = finders.find(rel_path)
            self.assertIsNotNone(found_path, f"Static file '{rel_path}' not found by finders")
            self.assertTrue(os.path.exists(found_path), f"File on disk '{found_path}' does not exist")

    # 7. No template contains inline <script> body or style= attribute
    def test_no_inline_scripts_or_styles_in_templates(self):
        templates_dir = os.path.join(settings.BASE_DIR, "apps", "web", "templates", "web")
        template_files = [f for f in os.listdir(templates_dir) if f.endswith(".html")]
        self.assertTrue(len(template_files) > 0)

        for filename in template_files:
            filepath = os.path.join(templates_dir, filename)
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()

            # Check no style=
            self.assertNotIn("style=", content, f"Inline style= found in {filename}")

            # Check no inline script content: any <script> must have src=
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

    # 8. No JavaScript file in static/web/js/ contains innerHTML, outerHTML, document.write, or eval(
    def test_no_unsafe_dom_sinks_in_js(self):
        js_dir = os.path.join(settings.BASE_DIR, "apps", "web", "static", "web", "js")
        js_files = [f for f in os.listdir(js_dir) if f.endswith(".js")]
        self.assertTrue(len(js_files) > 0)

        forbidden_sinks = ["innerHTML", "outerHTML", "document.write", "eval("]

        for filename in js_files:
            filepath = os.path.join(js_dir, filename)
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()

            for sink in forbidden_sinks:
                self.assertNotIn(sink, content, f"Forbidden sink '{sink}' found in {filename}")

    # 9. api.js is the only JS file containing fetch(
    def test_only_api_js_contains_fetch(self):
        js_dir = os.path.join(settings.BASE_DIR, "apps", "web", "static", "web", "js")
        js_files = [f for f in os.listdir(js_dir) if f.endswith(".js")]
        self.assertTrue(len(js_files) > 0)

        for filename in js_files:
            filepath = os.path.join(js_dir, filename)
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()

            if filename == "api.js":
                self.assertIn("fetch(", content, "api.js must contain fetch()")
            else:
                self.assertNotIn("fetch(", content, f"Disallowed fetch() found in {filename}")

    # 10. Existing API routes still resolve (anonymous /api/v1/opportunities/ returns 401/403, not 404)
    def test_existing_api_routes_still_resolve(self):
        response = self.client.get("/api/v1/opportunities/")
        self.assertIn(response.status_code, (401, 403), f"Expected 401/403, got {response.status_code}")
        self.assertNotEqual(response.status_code, 404)

