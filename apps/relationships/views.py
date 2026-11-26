from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.pagination import StandardResultsSetPagination
from apps.common.constants import CLOSED_STAGES
from apps.common.permissions import IsAdminOrBDManager, ReadOnly

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


MAX_VERIFICATION_NOTE = 300


def _rescore_open_leads(vessel):
    """A confirmed contact changes the score, so refresh this vessel's open leads."""
    from apps.opportunities.models import Opportunity
    from services.opportunity_service import recalculate_score

    for opp in Opportunity.objects.filter(vessel=vessel).exclude(stage__in=CLOSED_STAGES):
        recalculate_score(opp)


def _current_relationship_or_error(pk):
    rel = get_object_or_404(
        VesselRelationship.objects.select_related("vessel", "company", "verified_by"), pk=pk
    )
    if not rel.is_current:
        return rel, Response(
            {"detail": "This owner or manager link is no longer current."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    return rel, None


class VesselRelationshipVerifyAPIView(APIView):
    """POST: a team member confirms this owner/manager link (and may say how)."""

    permission_classes = [IsAdminOrBDManager]

    def post(self, request, pk):
        rel, error = _current_relationship_or_error(pk)
        if error:
            return error
        note = request.data.get("note", "")
        if note is None:
            note = ""
        if not isinstance(note, str):
            return Response({"note": ["Note must be text."]}, status=status.HTTP_400_BAD_REQUEST)
        note = note.strip()
        if len(note) > MAX_VERIFICATION_NOTE:
            return Response(
                {"note": [f"Ensure this field has no more than {MAX_VERIFICATION_NOTE} characters."]},
                status=status.HTTP_400_BAD_REQUEST,
            )
        rel.verified = True
        rel.verified_by = request.user
        rel.last_verified_date = timezone.now().date()
        rel.verification_note = note
        rel.save(update_fields=["verified", "verified_by", "last_verified_date", "verification_note", "updated_at"])
        _rescore_open_leads(rel.vessel)
        return Response(VesselRelationshipSerializer(rel).data)


class VesselRelationshipUnverifyAPIView(APIView):
    """POST: take the confirmation back (the link becomes unverified public data again)."""

    permission_classes = [IsAdminOrBDManager]

    def post(self, request, pk):
        rel, error = _current_relationship_or_error(pk)
        if error:
            return error
        rel.verified = False
        rel.verified_by = None
        rel.last_verified_date = None
        rel.verification_note = ""
        rel.save(update_fields=["verified", "verified_by", "last_verified_date", "verification_note", "updated_at"])
        _rescore_open_leads(rel.vessel)
        return Response(VesselRelationshipSerializer(rel).data)
