from rest_framework import viewsets

from apps.common.permissions import ReadOnly

from .models import VesselObservation
from .serializers import VesselObservationSerializer


class VesselObservationViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = VesselObservation.objects.select_related("vessel").all()
    serializer_class = VesselObservationSerializer
    permission_classes = [ReadOnly]
    filterset_fields = ["vessel", "source"]
