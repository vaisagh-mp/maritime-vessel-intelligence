"""
Role-based permission classes for the Vessel Intelligence API.

Two roles, implemented as Django Groups (names defined in settings):
  - Admin        — full control over all resources.
  - BD Manager   — read-everything + PATCH Opportunity stage + trigger enrichment.

Any Django superuser is treated as Admin regardless of group membership.
"""
from django.conf import settings
from rest_framework.permissions import SAFE_METHODS, BasePermission


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def is_admin(user) -> bool:
    """True if the user is a superuser OR a member of the Admin group."""
    return bool(
        user
        and user.is_authenticated
        and (
            user.is_superuser
            or user.groups.filter(name=settings.ROLE_ADMIN).exists()
        )
    )


def is_bd_manager(user) -> bool:
    """True if the user is a member of the BD Manager group."""
    return bool(
        user
        and user.is_authenticated
        and user.groups.filter(name=settings.ROLE_BD_MANAGER).exists()
    )


def is_admin_or_bd_manager(user) -> bool:
    """True if the user holds either the Admin or BD Manager role."""
    return is_admin(user) or is_bd_manager(user)


# ---------------------------------------------------------------------------
# Permission classes
# ---------------------------------------------------------------------------

class IsAdmin(BasePermission):
    """Admin-only access for any HTTP method."""

    message = "You must be an Admin to perform this action."

    def has_permission(self, request, view):
        return is_admin(request.user)


class IsAdminOrBDManagerReadOnly(BasePermission):
    """Both roles can read; write operations (POST/PUT/PATCH/DELETE) require Admin.

    Applied to Port and Company viewsets (master data).
    """

    message = "Write access to master data requires the Admin role."

    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        if request.method in SAFE_METHODS:
            return is_admin_or_bd_manager(request.user)
        return is_admin(request.user)


class IsAdminOrBDManager(BasePermission):
    """Either role may use any HTTP method that the viewset allows.

    Applied to Opportunity (read + PATCH stage) and the vessel enrich action.
    The viewset's http_method_names restriction (not this class) is responsible
    for excluding PUT so that only partial updates are possible.
    """

    message = "You must be an Admin or BD Manager to perform this action."

    def has_permission(self, request, view):
        return is_admin_or_bd_manager(request.user)


class ReadOnly(BasePermission):
    """GET/HEAD/OPTIONS only — for system-managed resources (Vessel,
    VesselObservation, EnrichmentLog, VesselRelationship) that must never
    be written via the API.

    Authentication is still required (handled by DEFAULT_PERMISSION_CLASSES
    → IsAuthenticated running first in DRF's permission check chain, but
    both classes must pass so we also check authenticated here defensively).
    """

    message = "This resource is read-only."

    def has_permission(self, request, view):
        return (
            request.user
            and request.user.is_authenticated
            and request.method in SAFE_METHODS
        )
