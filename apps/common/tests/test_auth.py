"""
Integration tests for JWT authentication and role-based authorization.

Covers every scenario defined in the Phase 1 add-on spec:

  - Anonymous request to any endpoint → 401
  - Authenticated user with no role   → 403 on protected write actions
  - BD Manager: read Port/Company (200), write Port/Company (403)
  - BD Manager: PATCH Opportunity stage (200), PUT Opportunity (405)
  - Admin / superuser: POST/PATCH/DELETE Port and Company (201/200/204)
"""
from django.contrib.auth.models import Group, User
from django.test import TestCase
from rest_framework.test import APIClient

from apps.companies.models import Company
from apps.ports.models import Port
from apps.vessels.models import Vessel
from apps.opportunities.models import Opportunity


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_user(username, *, superuser=False, groups=()):
    """Create a test user, optionally a superuser, optionally in named groups."""
    if superuser:
        user = User.objects.create_superuser(username, password="testpass123")
    else:
        user = User.objects.create_user(username, password="testpass123")
    for group_name in groups:
        group, _ = Group.objects.get_or_create(name=group_name)
        user.groups.add(group)
    return user


def _authed_client(user):
    """Return an APIClient already force-authenticated as *user*."""
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _port_payload(**overrides):
    defaults = dict(
        name="Fujairah",
        un_locode="AEFJR",
        latitude=25.12,
        longitude=56.34,
        anchorage_latitude=25.15,
        anchorage_longitude=56.40,
        geofence_radius_km=45,
    )
    defaults.update(overrides)
    return defaults


def _company_payload(**overrides):
    defaults = dict(name="Test Shipping Co", company_type="manager")
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Anonymous access
# ---------------------------------------------------------------------------

class AnonymousAccessTests(TestCase):
    """Every endpoint must return 401 for unauthenticated requests."""

    def setUp(self):
        self.client = APIClient()
        self.port = Port.objects.create(**_port_payload())

    def test_anonymous_get_ports_returns_401(self):
        response = self.client.get("/api/v1/ports/")
        self.assertEqual(response.status_code, 401)

    def test_anonymous_post_port_returns_401(self):
        response = self.client.post("/api/v1/ports/", _port_payload(un_locode="SGSIN"), format="json")
        self.assertEqual(response.status_code, 401)

    def test_anonymous_get_companies_returns_401(self):
        response = self.client.get("/api/v1/companies/")
        self.assertEqual(response.status_code, 401)

    def test_anonymous_get_vessels_returns_401(self):
        response = self.client.get("/api/v1/vessels/")
        self.assertEqual(response.status_code, 401)

    def test_anonymous_get_opportunities_returns_401(self):
        response = self.client.get("/api/v1/opportunities/")
        self.assertEqual(response.status_code, 401)

    def test_anonymous_get_observations_returns_401(self):
        response = self.client.get("/api/v1/observations/")
        self.assertEqual(response.status_code, 401)

    def test_anonymous_get_enrichment_returns_401(self):
        response = self.client.get("/api/v1/enrichment/")
        self.assertEqual(response.status_code, 401)


# ---------------------------------------------------------------------------
# No-role user (authenticated but no group)
# ---------------------------------------------------------------------------

class NoRoleUserTests(TestCase):
    """Authenticated user with no group must be forbidden on writes."""

    def setUp(self):
        self.user = _make_user("norole")
        self.client = _authed_client(self.user)
        self.port = Port.objects.create(**_port_payload())

    def test_no_role_get_ports_returns_403(self):
        # IsAdminOrBDManagerReadOnly: read requires at least one role
        response = self.client.get("/api/v1/ports/")
        self.assertEqual(response.status_code, 403)

    def test_no_role_post_port_returns_403(self):
        response = self.client.post("/api/v1/ports/", _port_payload(un_locode="SGSIN"), format="json")
        self.assertEqual(response.status_code, 403)

    def test_no_role_get_opportunities_returns_403(self):
        response = self.client.get("/api/v1/opportunities/")
        self.assertEqual(response.status_code, 403)


# ---------------------------------------------------------------------------
# BD Manager
# ---------------------------------------------------------------------------

class BDManagerPortTests(TestCase):
    """BD Manager can read Port master data but cannot write."""

    def setUp(self):
        self.user = _make_user("bdmgr", groups=["BD Manager"])
        self.client = _authed_client(self.user)
        self.port = Port.objects.create(**_port_payload())

    def test_bd_manager_get_ports_returns_200(self):
        response = self.client.get("/api/v1/ports/")
        self.assertEqual(response.status_code, 200)

    def test_bd_manager_post_port_returns_403(self):
        response = self.client.post("/api/v1/ports/", _port_payload(un_locode="SGSIN"), format="json")
        self.assertEqual(response.status_code, 403)

    def test_bd_manager_patch_port_returns_403(self):
        response = self.client.patch(
            f"/api/v1/ports/{self.port.id}/", {"name": "Fujairah Updated"}, format="json"
        )
        self.assertEqual(response.status_code, 403)

    def test_bd_manager_delete_port_returns_403(self):
        response = self.client.delete(f"/api/v1/ports/{self.port.id}/")
        self.assertEqual(response.status_code, 403)


class BDManagerCompanyTests(TestCase):
    """BD Manager can read Company master data but cannot write."""

    def setUp(self):
        self.user = _make_user("bdmgr2", groups=["BD Manager"])
        self.client = _authed_client(self.user)
        self.company = Company.objects.create(**_company_payload())

    def test_bd_manager_get_companies_returns_200(self):
        response = self.client.get("/api/v1/companies/")
        self.assertEqual(response.status_code, 200)

    def test_bd_manager_post_company_returns_403(self):
        response = self.client.post("/api/v1/companies/", _company_payload(name="Another Co"), format="json")
        self.assertEqual(response.status_code, 403)


class BDManagerOpportunityTests(TestCase):
    """BD Manager can PATCH Opportunity stage; PUT is 405 (method excluded)."""

    def setUp(self):
        self.user = _make_user("bdmgr3", groups=["BD Manager"])
        self.client = _authed_client(self.user)
        self.vessel = Vessel.objects.create(mmsi="111222333", name="BD TEST VESSEL")
        self.port = Port.objects.create(**_port_payload())
        self.opp = Opportunity.objects.create(
            vessel=self.vessel, port=self.port, zone="anchorage", stage="detected"
        )

    def test_bd_manager_get_opportunities_returns_200(self):
        response = self.client.get("/api/v1/opportunities/")
        self.assertEqual(response.status_code, 200)

    def test_bd_manager_patch_stage_returns_200(self):
        response = self.client.patch(
            f"/api/v1/opportunities/{self.opp.id}/", {"stage": "contacted"}, format="json"
        )
        self.assertEqual(response.status_code, 200)
        self.opp.refresh_from_db()
        self.assertEqual(self.opp.stage, "contacted")

    def test_put_opportunity_returns_405(self):
        """PUT is excluded by http_method_names — should be 405, not a permission error."""
        response = self.client.put(
            f"/api/v1/opportunities/{self.opp.id}/", {"stage": "contacted"}, format="json"
        )
        self.assertEqual(response.status_code, 405)


# ---------------------------------------------------------------------------
# Admin
# ---------------------------------------------------------------------------

class AdminPortTests(TestCase):
    """Admin (and superuser) can create, update, and delete Port master data."""

    def setUp(self):
        self.admin_user = _make_user("admin_grp", groups=["Admin"])
        self.superuser = _make_user("superuser_test", superuser=True)
        self.port = Port.objects.create(**_port_payload())

    def test_admin_group_post_port_returns_201(self):
        client = _authed_client(self.admin_user)
        response = client.post("/api/v1/ports/", _port_payload(un_locode="SGSIN", name="Singapore"), format="json")
        self.assertEqual(response.status_code, 201)

    def test_admin_group_patch_port_returns_200(self):
        client = _authed_client(self.admin_user)
        response = client.patch(
            f"/api/v1/ports/{self.port.id}/", {"name": "Fujairah Updated"}, format="json"
        )
        self.assertEqual(response.status_code, 200)

    def test_admin_group_delete_port_returns_204(self):
        client = _authed_client(self.admin_user)
        response = client.delete(f"/api/v1/ports/{self.port.id}/")
        self.assertEqual(response.status_code, 204)

    def test_superuser_post_port_without_group_returns_201(self):
        """Superuser has implicit Admin rights regardless of group membership."""
        client = _authed_client(self.superuser)
        response = client.post("/api/v1/ports/", _port_payload(un_locode="AEDXB", name="Dubai"), format="json")
        self.assertEqual(response.status_code, 201)


class AdminCompanyTests(TestCase):
    """Admin can create and manage Company master data."""

    def setUp(self):
        self.admin_user = _make_user("admin_co", groups=["Admin"])
        self.client = _authed_client(self.admin_user)

    def test_admin_post_company_returns_201(self):
        response = self.client.post("/api/v1/companies/", _company_payload(), format="json")
        self.assertEqual(response.status_code, 201)
