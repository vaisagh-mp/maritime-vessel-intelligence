from django.shortcuts import get_object_or_404
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.pagination import StandardResultsSetPagination
from apps.common.permissions import ReadOnly

from .models import VesselRelationship
from .serializers import VesselRelationshipSerializer


class VesselRelationshipListAPIView(APIView):
    """Read-only — system-managed, created exclusively by the enrichment service."""

    permission_classes = [ReadOnly]

    def get(self, request):
        qs = VesselRelationship.objects.select_related("vessel", "company").all()

        vessel_id = request.query_params.get("vessel")
        if vessel_id:
            qs = qs.filter(vessel_id=vessel_id)

        company_id = request.query_params.get("company")
        if company_id:
            qs = qs.filter(company_id=company_id)

        is_current = request.query_params.get("is_current")
        if is_current is not None:
            if is_current.lower() in ("true", "1"):
                qs = qs.filter(is_current=True)
            elif is_current.lower() in ("false", "0"):
                qs = qs.filter(is_current=False)

        role = request.query_params.get("role")
        if role:
            qs = qs.filter(role=role)

        verified = request.query_params.get("verified")
        if verified is not None:
            if verified.lower() in ("true", "1"):
                qs = qs.filter(verified=True)
            elif verified.lower() in ("false", "0"):
                qs = qs.filter(verified=False)

        paginator = StandardResultsSetPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        if page is not None:
            serializer = VesselRelationshipSerializer(page, many=True)
            return paginator.get_paginated_response(serializer.data)
        serializer = VesselRelationshipSerializer(qs, many=True)
        return Response(serializer.data)


class VesselRelationshipDetailAPIView(APIView):
    """Read-only — system-managed."""

    permission_classes = [ReadOnly]

    def get(self, request, pk):
        rel = get_object_or_404(
            VesselRelationship.objects.select_related("vessel", "company"), pk=pk
        )
        serializer = VesselRelationshipSerializer(rel)
        return Response(serializer.data)
