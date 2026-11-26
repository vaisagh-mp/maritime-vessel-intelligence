"""API views for the live refresh button (Admin and BD Manager only)."""
from django.shortcuts import get_object_or_404
from apps.vessels.models import Vessel
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.permissions import IsAdminOrBDManager

from . import refresh
from .models import IngestRun


class IngestRefreshView(APIView):
    """POST {"port": "SGSIN"} starts ONE live Expected Arrivals call."""

    permission_classes = [IsAdminOrBDManager]

    def post(self, request):
        body = request.data if hasattr(request.data, "get") else {}
        code, payload, headers = refresh.start_refresh(request.user, body.get("port"))
        return Response(payload, status=code, headers=headers)


class IngestStatusView(APIView):
    permission_classes = [IsAdminOrBDManager]

    def get(self, request):
        return Response(refresh.status_payload())


class IngestRunDetailView(APIView):
    permission_classes = [IsAdminOrBDManager]

    def get(self, request, pk):
        refresh.expire_stale_runs()
        run = get_object_or_404(IngestRun.objects.select_related("requested_by"), pk=pk)
        return Response(refresh.serialize_run(run), status=status.HTTP_200_OK)


class VesselOwnerLookupView(APIView):
    """POST: look up owners and managers for ONE vessel (uses the manual daily share)."""

    permission_classes = [IsAdminOrBDManager]

    def post(self, request, pk):
        vessel = get_object_or_404(Vessel, pk=pk)
        body = request.data if hasattr(request.data, "get") else {}
        code, payload = refresh.manual_owner_lookup(request.user, vessel, force=bool(body.get("force")))
        return Response(payload, status=code)
