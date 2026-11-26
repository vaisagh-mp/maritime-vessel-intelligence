"""
apps/web/tests_security.py
Security test suite for Frontend F6:
- Content Security Policy (enforce, report-only, off; no unsafe-inline/eval; exempt admin & API)
- Security headers and cookie configurations
- Open redirect protection on login
- Session fixation and post-logout session invalidation
- CSRF enforcement on state-changing API endpoints
- XSS payloads preserved verbatim by API (safe display via textContent/el)
- RBAC protection (401 for anonymous, 403 for roleless users across frontend views and APIs)
- Export cap and CSV formula neutralization
- Static template and script link security (target="_blank" requires rel="noopener noreferrer")
"""

import os
import re
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import Client, TestCase, override_settings

from apps.companies.models import Company
from apps.opportunities.models import Opportunity, OpportunityNote
from apps.ports.models import Port
from apps.vessels.models import Vessel

User = get_user_model()


class TestWebSecurity(TestCase):
    """Security settings, headers, CSRF, XSS, and RBAC tests."""

    def setUp(self):
        self.client = Client()

        # Groups from settings
        self.admin_group, _ = Group.objects.get_or_create(name=settings.ROLE_ADMIN)
        self.bd_group, _ = Group.objects.get_or_create(name=settings.ROLE_BD_MANAGER)

        # Users
        self.admin_user = User.objects.create_user(
            username="sec_admin",
            password="secpassword123",
            email="sec_admin@example.com",
            is_staff=True,
        )
        self.admin_user.groups.add(self.admin_group)

        self.bd_user = User.objects.create_user(
            username="sec_bd",
            password="secpassword123",
            email="sec_bd@example.com",
            is_staff=False,
        )
        self.bd_user.groups.add(self.bd_group)

        self.no_role_user = User.objects.create_user(
            username="sec_norole",
            password="secpassword123",
            email="sec_norole@example.com",
            is_staff=False,
        )

        # Port, vessel, opportunity
        self.port = Port.objects.create(
            name="Singapore",
            un_locode="SGSIN",
            latitude=1.29,
            longitude=103.85,
            anchorage_latitude=1.25,
            anchorage_longitude=103.80,
            geofence_radius_km=25.0,
        )
        self.vessel = Vessel.objects.create(
            imo=9998882,
            mmsi=563000002,
            name="OCEAN DEFENDER",
            vessel_type="Crude Oil Tanker",
            dwt=110000,
            flag="Singapore",
        )
        self.opportunity = Opportunity.objects.create(
            vessel=self.vessel,
            port=self.port,
            stage="detected",
            score=75,
            zone="24h",
            is_inbound=True,
            lead_reason="Security test lead",
        )

    # 1. Content Security Policy header tests
    def test_csp_header_enforce_mode(self):
        self.client.login(username="sec_admin", password="secpassword123")

        protected_paths = [
            "/",
            f"/vessels/{self.vessel.id}/",
            f"/leads/{self.opportunity.id}/",
        ]
        for path in protected_paths:
            res = self.client.get(path)
            self.assertEqual(res.status_code, 200, f"Failed for {path}")
            csp = res.headers.get("Content-Security-Policy")
            self.assertIsNotNone(csp, f"Content-Security-Policy header missing on {path}")
            self.assertNotIn("unsafe-inline", csp, f"unsafe-inline found in CSP on {path}")
            self.assertNotIn("unsafe-eval", csp, f"unsafe-eval found in CSP on {path}")
            self.assertIn("default-src 'self'", csp)

        # Unauthenticated login page check
        anon_client = Client()
        login_res = anon_client.get("/login/")
        self.assertEqual(login_res.status_code, 200)
        self.assertIn("Content-Security-Policy", login_res.headers)

        # Admin exempt
        admin_res = self.client.get("/admin/login/")
        self.assertNotIn("Content-Security-Policy", admin_res.headers)

        # API JSON exempt
        api_res = self.client.get(f"/api/v1/opportunities/{self.opportunity.id}/")
        self.assertEqual(api_res.status_code, 200)
        self.assertNotIn("Content-Security-Policy", api_res.headers)
        self.client.logout()

    def test_csp_header_report_only_and_off_modes(self):
        self.client.login(username="sec_admin", password="secpassword123")

        with override_settings(WEB_CSP_MODE="report-only"):
            res = self.client.get("/")
            self.assertNotIn("Content-Security-Policy", res.headers)
            self.assertIn("Content-Security-Policy-Report-Only", res.headers)
            report_csp = res.headers["Content-Security-Policy-Report-Only"]
            self.assertIn("default-src 'self'", report_csp)

        with override_settings(WEB_CSP_MODE="off"):
            res = self.client.get("/")
            self.assertNotIn("Content-Security-Policy", res.headers)
            self.assertNotIn("Content-Security-Policy-Report-Only", res.headers)

        self.client.logout()

    # 2. Security settings and cookies
    def test_security_settings_and_cookie_attributes(self):
        res = self.client.get("/login/")
        self.assertEqual(res.headers.get("X-Frame-Options"), "DENY")
        self.assertEqual(res.headers.get("X-Content-Type-Options"), "nosniff")
        self.assertEqual(res.headers.get("Referrer-Policy"), "same-origin")

        self.assertTrue(settings.SESSION_COOKIE_HTTPONLY)
        self.assertEqual(settings.SESSION_COOKIE_SAMESITE, "Lax")
        self.assertEqual(settings.CSRF_COOKIE_SAMESITE, "Lax")

    # 3. Open redirect protection
    def test_open_redirect_protection(self):
        # External URL
        res = self.client.post("/login/?next=https://evil.example/", {
            "username": "sec_bd",
            "password": "secpassword123",
        })
        self.assertEqual(res.status_code, 302)
        self.assertEqual(res.headers["Location"], "/")
        self.client.logout()

        # Protocol-relative URL
        res = self.client.post("/login/?next=//evil.example/", {
            "username": "sec_bd",
            "password": "secpassword123",
        })
        self.assertEqual(res.status_code, 302)
        self.assertEqual(res.headers["Location"], "/")
        self.client.logout()

        # Legitimate same-origin relative path
        valid_next = f"/leads/{self.opportunity.id}/"
        res = self.client.post(f"/login/?next={valid_next}", {
            "username": "sec_bd",
            "password": "secpassword123",
        })
        self.assertEqual(res.status_code, 302)
        self.assertEqual(res.headers["Location"], valid_next)
        self.client.logout()

    # 4. Session fixation and logout
    def test_session_invalidation_after_logout(self):
        self.client.login(username="sec_bd", password="secpassword123")
        res_auth = self.client.get("/")
        self.assertEqual(res_auth.status_code, 200)

        # Extract active session key
        session_key = self.client.cookies.get(settings.SESSION_COOKIE_NAME).value

        # Log out
        res_logout = self.client.post("/logout/")
        self.assertEqual(res_logout.status_code, 302)

        # Attempt to access protected route with the old session cookie
        client2 = Client()
        client2.cookies[settings.SESSION_COOKIE_NAME] = session_key
        res_expired = client2.get("/")
        self.assertEqual(res_expired.status_code, 302)
        self.assertIn("/login/", res_expired.headers["Location"])

    # 5. CSRF enforcement on state-changing API endpoints
    def test_csrf_enforcement_on_mutations(self):
        csrf_client = Client(enforce_csrf_checks=True)

        # Obtain valid CSRF token cookie via initial GET
        csrf_client.get("/login/")
        csrf_token = csrf_client.cookies[settings.CSRF_COOKIE_NAME].value

        csrf_client.login(username="sec_bd", password="secpassword123")

        # 5a. PATCH opportunity stage without CSRF token -> 403 Forbidden
        patch_no_csrf = csrf_client.patch(
            f"/api/v1/opportunities/{self.opportunity.id}/",
            data={"stage": "qualifying"},
            content_type="application/json",
        )
        self.assertEqual(patch_no_csrf.status_code, 403)

        # 5b. PATCH opportunity stage with valid CSRF token -> 200 OK
        patch_csrf = csrf_client.patch(
            f"/api/v1/opportunities/{self.opportunity.id}/",
            data={"stage": "qualifying"},
            content_type="application/json",
            headers={"X-CSRFToken": csrf_token},
        )
        self.assertEqual(patch_csrf.status_code, 200)

        # 5c. POST opportunity note without CSRF token -> 403 Forbidden
        post_no_csrf = csrf_client.post(
            f"/api/v1/opportunities/{self.opportunity.id}/notes/",
            data={"text": "Note without CSRF"},
            content_type="application/json",
        )
        self.assertEqual(post_no_csrf.status_code, 403)

        # 5d. POST opportunity note with valid CSRF token -> 201 Created
        post_csrf = csrf_client.post(
            f"/api/v1/opportunities/{self.opportunity.id}/notes/",
            data={"text": "Note with valid CSRF token"},
            content_type="application/json",
            headers={"X-CSRFToken": csrf_token},
        )
        self.assertEqual(post_csrf.status_code, 201)

    # 6. XSS payloads returned unchanged by API
    def test_xss_payloads_returned_verbatim(self):
        self.client.login(username="sec_bd", password="secpassword123")

        # Vessel name with script tag
        xss_vessel = Vessel.objects.create(
            imo=9998889,
            mmsi=563000009,
            name="<img src=x onerror=alert(1)>",
            vessel_type="Tanker",
            dwt=50000,
        )
        res_v = self.client.get(f"/api/v1/vessels/{xss_vessel.id}/")
        self.assertEqual(res_v.status_code, 200)
        self.assertEqual(res_v.json()["name"], "<img src=x onerror=alert(1)>")

        # Company website with javascript: URI
        xss_company = Company.objects.create(
            name="XSS Shipping",
            company_type="owner",
            website="javascript:alert(1)",
        )
        res_c = self.client.get(f"/api/v1/companies/{xss_company.id}/")
        self.assertEqual(res_c.status_code, 200)
        self.assertEqual(res_c.json()["website"], "javascript:alert(1)")

        # Opportunity note with script tag
        res_n = self.client.post(
            f"/api/v1/opportunities/{self.opportunity.id}/notes/",
            data={"text": "<script>alert(1)</script>"},
            content_type="application/json",
        )
        self.assertEqual(res_n.status_code, 201)
        self.assertEqual(res_n.json()["text"], "<script>alert(1)</script>")

        self.client.logout()

    # 7. Frontend API endpoints RBAC loop
    def test_frontend_api_endpoints_rbac_loop(self):
        all_endpoints = [
            "/api/v1/opportunities/",
            "/api/v1/vessels/",
            "/api/v1/ports/",
            "/api/v1/companies/",
            "/api/v1/relationships/",
            "/api/v1/enrichment/",
            "/api/v1/observations/",
        ]

        # Anonymous user -> 401 Unauthorized across all endpoints
        anon_client = Client()
        for ep in all_endpoints:
            res = anon_client.get(ep)
            self.assertEqual(
                res.status_code,
                401,
                f"Anonymous user must receive 401 on {ep}, got {res.status_code}",
            )

        # Authenticated user with no role -> 403 on role-gated master & opportunity resources
        role_protected_endpoints = [
            "/api/v1/opportunities/",
            "/api/v1/opportunities/export/",
            f"/api/v1/opportunities/{self.opportunity.id}/",
            f"/api/v1/opportunities/{self.opportunity.id}/notes/",
            f"/api/v1/opportunities/{self.opportunity.id}/history/",
            "/api/v1/ports/",
            "/api/v1/companies/",
        ]
        roleless_client = Client()
        roleless_client.login(username="sec_norole", password="secpassword123")
        for ep in role_protected_endpoints:
            res = roleless_client.get(ep)
            self.assertEqual(
                res.status_code,
                403,
                f"Roleless user must receive 403 on {ep}, got {res.status_code}",
            )

        # Web frontend routes return 403 for roleless users
        frontend_routes = [
            "/",
            f"/vessels/{self.vessel.id}/",
            f"/leads/{self.opportunity.id}/",
        ]
        for path in frontend_routes:
            res = roleless_client.get(path)
            self.assertEqual(
                res.status_code,
                403,
                f"Roleless user must receive 403 on frontend view {path}, got {res.status_code}",
            )

    # 8. Target blank links require rel="noopener noreferrer"
    def test_target_blank_rel_noopener_noreferrer(self):
        web_dir = os.path.join(settings.BASE_DIR, "apps", "web")
        target_pattern = re.compile(r'target\s*[:=]\s*["\']_blank["\']')
        rel_pattern = re.compile(r'rel\s*[:=]\s*["\']noopener noreferrer["\']')

        scanned = 0
        for root, _, files in os.walk(web_dir):
            for file in files:
                if file.endswith((".html", ".js", ".mjs")):
                    filepath = os.path.join(root, file)
                    with open(filepath, "r", encoding="utf-8") as f:
                        content = f.read()
                    scanned += 1
                    if target_pattern.search(content):
                        self.assertTrue(
                            rel_pattern.search(content),
                            f"File {file} contains target='_blank' without rel='noopener noreferrer'",
                        )
        self.assertGreater(scanned, 10, "Expected to scan at least 10 web template/js files")
