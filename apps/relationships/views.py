from rest_framework import viewsets

from apps.common.permissions import ReadOnly

from .models import VesselRelationship
from .serializers import VesselRelationshipSerializer


class VesselRelationshipViewSet(viewsets.ReadOnlyModelViewSet):
    """Read-only — system-managed, created exclusively by the enrichment service."""

    queryset = VesselRelationship.objects.select_related("vessel", "company").all()
    serializer_class = VesselRelationshipSerializer
    permission_classes = [ReadOnly]
    filterset_fields = ["role", "verified"]
