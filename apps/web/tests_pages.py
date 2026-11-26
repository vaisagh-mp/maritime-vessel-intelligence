"""Tests for the sidebar layout, Dashboard, priority lists and Business Developers pages."""
import re

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import Client, TestCase, override_settings

User = get_user_model()


@override_settings(INGEST_REFRESH_AIS_ENABLED=True)
class PagesTests(TestCase):
    def setUp(self):
        admin_group, _ = Group.objects.get_or_create(name=settings.ROLE_ADMIN)
        bd_group, _ = Group.objects.get_or_create(name=settings.ROLE_BD_MANAGER)
        self.admin = User.objects.create_user("boss", password="pw-Secret-123", first_name="Priya", last_name="Nair")
        self.admin.groups.add(admin_group)
        self.bd = User.objects.create_user("asha", password="pw-Secret-123")
        self.bd.groups.add(bd_group)
        self.nobody = User.objects.create_user("nobody", password="pw-Secret-123")

    def as_user(self, name):
        c = Client()
        c.login(username=name, password="pw-Secret-123")
        return c

    # ----- dashboard -----
    def test_dashboard_welcomes_user_by_full_name(self):
        html = self.as_user("boss").get("/").content.decode()
        self.assertIn("Welcome, Priya Nair", html)
        self.assertIn('id="stat-cards"', html)
        self.assertIn('id="table-host"', html)
        for panel in ("panel-attention", "panel-pipeline", "panel-ports", "panel-activity", "panel-refresh"):
            self.assertIn(f'id="{panel}"', html)

    def test_dashboard_falls_back_to_username(self):
        self.assertIn("Welcome, asha", self.as_user("asha").get("/").content.decode())

    def test_dashboard_has_live_refresh_controls(self):
        html = self.as_user("boss").get("/").content.decode()
        for needle in ('id="btn-live-refresh"', 'id="btn-refresh"', 'id="filter-port"', 'id="live-refresh-status"'):
            self.assertIn(needle, html)

    # ----- sidebar -----
    def test_sidebar_links_for_admin(self):
        html = self.as_user("boss").get("/").content.decode()
        for href in ('href="/"', 'href="/priority/24h/"', 'href="/priority/72h/"',
                     'href="/priority/anchorage/"', 'href="/business-developers/"'):
            self.assertIn(href, html)
        self.assertIn("Add BD / Business Developer", html)
        self.assertIn('class="sidebar"', html)

    def test_sidebar_hides_business_developers_for_bd_manager(self):
        html = self.as_user("asha").get("/").content.decode()
        self.assertIn('href="/priority/24h/"', html)
        self.assertNotIn('href="/business-developers/"', html)
        self.assertNotIn("Add BD / Business Developer", html)

    def test_no_sidebar_for_user_without_role_or_on_login(self):
        res = self.as_user("nobody").get("/")
        self.assertEqual(res.status_code, 403)
        self.assertNotIn('class="sidebar"', res.content.decode())
        self.assertNotIn('class="sidebar"', Client().get("/login/").content.decode())

    def test_active_link_is_marked(self):
        c = self.as_user("boss")
        home = c.get("/").content.decode()
        self.assertRegex(home, r'<a href="/" class="side-link active" aria-current="page">')
        seventy = c.get("/priority/72h/").content.decode()
        self.assertRegex(seventy, r'href="/priority/72h/" class="side-sublink active" aria-current="page"')
        self.assertEqual(len(re.findall(r'aria-current="page"', seventy)), 1)
        bds = c.get("/business-developers/").content.decode()
        self.assertRegex(bds, r'href="/business-developers/" class="side-link active" aria-current="page"')

    # ----- priority pages -----
    def test_priority_pages_render(self):
        c = self.as_user("asha")
        expected = {"24h": "24 hour priority", "72h": "72 hour approach", "anchorage": "Anchorage / port"}
        for zone, title in expected.items():
            res = c.get(f"/priority/{zone}/")
            self.assertEqual(res.status_code, 200, zone)
            html = res.content.decode()
            self.assertIn(f'<h1 id="list-title">{title}</h1>', html)
            self.assertIn(f'data-zone="{zone}"', html)
            self.assertIn('id="reset-filters"', html)
            self.assertIn('id="btn-live-refresh"', html)

    def test_ais_off_hides_anchorage_everywhere(self):
        with self.settings(INGEST_REFRESH_AIS_ENABLED=False):
            c = self.as_user("asha")
            html = c.get("/").content.decode()
            self.assertNotIn('href="/priority/anchorage/"', html)
            self.assertIn('data-ais="0"', html)
            self.assertEqual(c.get("/priority/anchorage/").status_code, 404)
            self.assertEqual(c.get("/priority/24h/").status_code, 200)

    def test_ais_on_shows_anchorage(self):
        html = self.as_user("asha").get("/").content.decode()
        self.assertIn('href="/priority/anchorage/"', html)
        self.assertIn('data-ais="1"', html)

    def test_unknown_priority_zone_is_404(self):
        self.assertEqual(self.as_user("asha").get("/priority/week/").status_code, 404)

    def test_priority_index_redirects_to_24h(self):
        res = self.as_user("asha").get("/priority/")
        self.assertEqual(res.status_code, 302)
        self.assertEqual(res["Location"], "/priority/24h/")

    def test_priority_pages_need_login_and_role(self):
        self.assertEqual(Client().get("/priority/24h/").status_code, 302)
        self.assertEqual(self.as_user("nobody").get("/priority/24h/").status_code, 403)

    # ----- business developers page -----
    def test_business_developers_page_is_admin_only(self):
        self.assertEqual(Client().get("/business-developers/").status_code, 302)
        self.assertEqual(self.as_user("nobody").get("/business-developers/").status_code, 403)
        res = self.as_user("asha").get("/business-developers/")
        self.assertEqual(res.status_code, 403)
        self.assertIn("Only an Admin can open this page", res.content.decode())
        ok = self.as_user("boss").get("/business-developers/")
        self.assertEqual(ok.status_code, 200)

    def test_business_developers_page_markup(self):
        html = self.as_user("boss").get("/business-developers/").content.decode()
        self.assertIn("<h1>Business Developers</h1>", html)
        for needle in ('id="btn-add-bd"', 'id="bd-table-host"', 'id="form-add"', 'id="form-edit"',
                       'id="form-password"', 'id="dlg-confirm"', 'name="username"', 'name="password"'):
            self.assertIn(needle, html)
        self.assertIn(f'data-me-id="{self.admin.id}"', html)

    # ----- back links -----
    def test_lead_and_vessel_back_links_point_to_priority(self):
        from apps.opportunities.models import Opportunity
        from apps.ports.models import Port
        from apps.vessels.models import Vessel

        port = Port.objects.create(
            name="Singapore", un_locode="SGSIN", latitude=1.29, longitude=103.85,
            anchorage_latitude=1.25, anchorage_longitude=103.8, geofence_radius_km=30.0, active=True)
        v = Vessel.objects.create(imo="9111111", mmsi="400000001", name="V1")
        opp = Opportunity.objects.create(vessel=v, port=port, zone="24h")
        c = self.as_user("asha")
        for url in (f"/leads/{opp.id}/", f"/vessels/{v.id}/"):
            html = c.get(url).content.decode()
            self.assertIn('href="/priority/24h/" id="back-to-board-link"', html)
