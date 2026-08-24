from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.common.permissions import IsAdminOrBDManager, ReadOnly
from apps.enrichment.services import trigger_manual_enrichment
from apps.observations.models import VesselObservation
from apps.observations.serializers import VesselObservationSerializer

from .models import Vessel
from .serializers import VesselSerializer


class VesselViewSet(viewsets.ReadOnlyModelViewSet):
    """Read-only — system-managed. Vessels are created/updated by discovery only.

    Exception: the `enrich` action (POST) is writable and requires at least
    the BD Manager role.
    """

    queryset = Vessel.objects.all()
    serializer_class = VesselSerializer
    permission_classes = [ReadOnly]
    filterset_fields = ["vessel_type"]
    search_fields = ["name", "mmsi", "imo"]

    @action(detail=True, methods=["get"])
    def observations(self, request, pk=None):
        vessel = self.get_object()
        qs = VesselObservation.objects.filter(vessel=vessel).order_by("-timestamp")
        page = self.paginate_queryset(qs)
        serializer = VesselObservationSerializer(page or qs, many=True)
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)

    @action(
        detail=True,
        methods=["post"],
        permission_classes=[IsAdminOrBDManager],
    )
    def enrich(self, request, pk=None):
        """Manually flag a vessel for enrichment (POST /api/v1/vessels/{id}/enrich/).

        This only enqueues/records the request — actual enrichment runs via the
        enrichment task/queue, kept separate from the request/response cycle.
        Requires Admin or BD Manager role (overrides the viewset-level ReadOnly class).
        """
        vessel = self.get_object()
        result = trigger_manual_enrichment(vessel)
        return Response(result, status=202)
