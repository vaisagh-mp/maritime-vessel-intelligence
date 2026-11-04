"""
apps/common/auth_views.py

Authentication and identity introspection endpoints.
"""

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.permissions import is_admin, is_bd_manager


class MeView(APIView):
    """GET /api/v1/auth/me/ — Return identity and role of the authenticated user."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        if is_admin(user):
            role = "admin"
        elif is_bd_manager(user):
            role = "bd_manager"
        else:
            role = "none"

        return Response(
            {
                "id": user.id,
                "username": user.username,
                "full_name": user.get_full_name(),
                "role": role,
                "is_staff": user.is_staff,
            }
        )

