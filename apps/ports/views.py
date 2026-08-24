from rest_framework import viewsets

from apps.common.permissions import IsAdminOrBDManagerReadOnly

from .models import Port
from .serializers import PortSerializer


class PortViewSet(viewsets.ModelViewSet):
    """Full read/write — Admin-only writes; BD Managers can read.
    Only `active` ports are polled by discovery.
    """

    queryset = Port.objects.all()
    serializer_class = PortSerializer
    permission_classes = [IsAdminOrBDManagerReadOnly]
    filterset_fields = ["active"]
    search_fields = ["name", "un_locode"]
