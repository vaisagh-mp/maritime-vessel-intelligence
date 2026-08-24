from rest_framework import viewsets

from apps.common.permissions import ReadOnly

from .models import EnrichmentLog
from .serializers import EnrichmentLogSerializer


class EnrichmentLogViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = EnrichmentLog.objects.select_related("vessel").all()
    serializer_class = EnrichmentLogSerializer
    permission_classes = [ReadOnly]
    filterset_fields = ["endpoint_called", "success", "vessel"]
