"""
apps/web/context_processors.py

Context processors for web app templates.
"""

from apps.common.permissions import is_admin, is_bd_manager


def web_user_role(request):
    """Expose web_role ("admin" | "bd_manager" | "none") to templates."""
    user = getattr(request, "user", None)
    if user and user.is_authenticated:
        if is_admin(user):
            return {"web_role": "admin"}
        elif is_bd_manager(user):
            return {"web_role": "bd_manager"}
    return {"web_role": "none"}
