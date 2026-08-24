from rest_framework import viewsets

from apps.common.permissions import IsAdminOrBDManagerReadOnly

from .models import Company
from .serializers import CompanySerializer


class CompanyViewSet(viewsets.ModelViewSet):
    """Full read/write — Admin-only writes; BD Managers can read."""

    queryset = Company.objects.all()
    serializer_class = CompanySerializer
    permission_classes = [IsAdminOrBDManagerReadOnly]
    filterset_fields = ["company_type", "priority"]
    search_fields = ["name", "email"]
