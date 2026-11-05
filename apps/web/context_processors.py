"""
apps/web/context_processors.py

Context processors for web app templates:
- web_user_role: Exposes web_role ("admin" | "bd_manager" | "none") and static_version
- web_static_version: Exposes static_version cache-busting timestamp
"""

import os
from django.conf import settings
from apps.common.permissions import is_admin, is_bd_manager

_CACHED_STATIC_VERSION = None


def compute_static_version():
    """Calculate highest modification timestamp (int) of all static assets in apps/web/static/web/."""
    static_dir = os.path.join(settings.BASE_DIR, "apps", "web", "static", "web")
    max_mtime = 0
    if os.path.exists(static_dir):
        for root, _, files in os.walk(static_dir):
            for file in files:
                try:
                    mtime = int(os.path.getmtime(os.path.join(root, file)))
                    if mtime > max_mtime:
                        max_mtime = mtime
                except OSError:
                    pass
    return str(max_mtime or 1)


def get_static_version():
    """Return cached static version; recomputes on each request when DEBUG=True."""
    global _CACHED_STATIC_VERSION
    if getattr(settings, "DEBUG", False):
        return compute_static_version()
    if _CACHED_STATIC_VERSION is None:
        _CACHED_STATIC_VERSION = compute_static_version()
    return _CACHED_STATIC_VERSION


def web_static_version(request=None):
    """Expose static_version string to templates."""
    return {"static_version": get_static_version()}


def web_user_role(request):
    """Expose web_role ("admin" | "bd_manager" | "none") and static_version to templates."""
    role = "none"
    user = getattr(request, "user", None)
    if user and user.is_authenticated:
        if is_admin(user):
            role = "admin"
        elif is_bd_manager(user):
            role = "bd_manager"

    return {
        "web_role": role,
        "static_version": get_static_version(),
    }
