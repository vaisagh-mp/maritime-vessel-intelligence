import django_filters
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils.dateparse import parse_datetime
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.constants import CLOSED_STAGES, STAGE_LOST, STAGE_WON
from apps.common.pagination import StandardResultsSetPagination
from apps.common.permissions import IsAdminOrBDManager
from services.opportunity_service import recalculate_score

from .models import Opportunity, OpportunityNote, OpportunityStageChange
from .serializers import (
    OpportunityNoteSerializer,
    OpportunitySerializer,
    OpportunityStageChangeSerializer,
    OpportunityStageUpdateSerializer,
)


class OpportunityBandFilter(django_filters.FilterSet):
    """Custom filterset that adds a `band` query parameter alongside the
    existing stage/zone/port/vessel filters.  Since `band` is not a stored
    column, we translate it into score-range lookups against SCORE_BANDS."""

    band = django_filters.CharFilter(
        method="filter_band", label="Priority band (HOT/HIGH/MEDIUM/LOW)"
    )

    class Meta:
        model = Opportunity
        fields = ["stage", "zone", "port", "vessel"]

    def filter_band(self, queryset, name, value):
        from django.conf import settings

        value_upper = value.upper()
        bands = settings.SCORE_BANDS  # [(80, "HOT"), (60, "HIGH"), ...]

        for i, (threshold, label) in enumerate(bands):
            if label == value_upper:
                upper = bands[i - 1][0] if i > 0 else None
                if upper is not None:
                    return queryset.filter(score__gte=threshold, score__lt=upper)
                return queryset.filter(score__gte=threshold)

        return queryset.none()


class OpportunityListAPIView(APIView):
    """Read-only list for Opportunities with extended search and date filters."""

    permission_classes = [IsAdminOrBDManager]

    def get(self, request):
        qs = Opportunity.objects.select_related("vessel", "port").all()

        filterset = OpportunityBandFilter(request.GET, queryset=qs)
        if filterset.is_valid():
            qs = filterset.qs

        # open=true|false filter
        open_param = request.query_params.get("open")
        if open_param is not None:
            if open_param.lower() in ("true", "1"):
                qs = qs.exclude(stage__in=CLOSED_STAGES)
            elif open_param.lower() in ("false", "0"):
                qs = qs.filter(stage__in=CLOSED_STAGES)

        # is_inbound=true|false filter
        inbound_param = request.query_params.get("is_inbound")
        if inbound_param is not None:
            if inbound_param.lower() in ("true", "1"):
                qs = qs.filter(is_inbound=True)
            elif inbound_param.lower() in ("false", "0"):
                qs = qs.filter(is_inbound=False)

        # q search filter: vessel name (icontains), IMO/MMSI (istartswith)
        q = request.query_params.get("q", "").strip()
        if q:
            qs = qs.filter(
                Q(vessel__name__icontains=q)
                | Q(vessel__imo__istartswith=q)
                | Q(vessel__mmsi__istartswith=q)
            )

        # eta_before / eta_after datetime filters with 400 on invalid format
        eta_before = request.query_params.get("eta_before")
        if eta_before:
            dt_before = parse_datetime(eta_before)
            if dt_before is None:
                return Response(
                    {"eta_before": ["Invalid ISO datetime format for eta_before."]},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            qs = qs.filter(eta__lte=dt_before)

        eta_after = request.query_params.get("eta_after")
        if eta_after:
            dt_after = parse_datetime(eta_after)
            if dt_after is None:
                return Response(
                    {"eta_after": ["Invalid ISO datetime format for eta_after."]},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            qs = qs.filter(eta__gte=dt_after)

        ordering = request.query_params.get("ordering", "-score")
        valid_ordering_fields = [
            "score", "-score", "detected_at", "-detected_at", "eta", "-eta"
        ]
        if ordering in valid_ordering_fields:
            qs = qs.order_by(ordering)
        else:
            qs = qs.order_by("-score")

        paginator = StandardResultsSetPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        if page is not None:
            serializer = OpportunitySerializer(page, many=True)
            return paginator.get_paginated_response(serializer.data)
        serializer = OpportunitySerializer(qs, many=True)
        return Response(serializer.data)


class OpportunityDetailAPIView(APIView):
    """Read-only except for PATCH (stage-only update + optional note). PUT is not supported (405)."""

    permission_classes = [IsAdminOrBDManager]

    def get_object(self, pk):
        return get_object_or_404(
            Opportunity.objects.select_related("vessel", "port"), pk=pk
        )

    def get(self, request, pk):
        opp = self.get_object(pk)
        serializer = OpportunitySerializer(opp)
        return Response(serializer.data)

    def patch(self, request, pk):
        opp = self.get_object(pk)
        old_stage = opp.stage

        # Optional note validation before opening transaction
        note_text = None
        if "note" in request.data:
            raw_note = request.data.get("note")
            if raw_note is None or not str(raw_note).strip():
                return Response(
                    {"note": ["Note text cannot be empty."]},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            note_text = str(raw_note).strip()
            if len(note_text) > 2000:
                return Response(
                    {"note": ["Ensure this field has no more than 2000 characters."]},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        serializer = OpportunityStageUpdateSerializer(opp, data=request.data, partial=True)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            opportunity = serializer.save()
            stage_changed = (old_stage != opportunity.stage)

            if stage_changed:
                OpportunityStageChange.objects.create(
                    opportunity=opportunity,
                    from_stage=old_stage,
                    to_stage=opportunity.stage,
                    changed_by=request.user if request.user.is_authenticated else None,
                )

            if note_text is not None:
                OpportunityNote.objects.create(
                    opportunity=opportunity,
                    author=request.user if request.user.is_authenticated else None,
                    text=note_text,
                )

            recalculate_score(opportunity)

            if opportunity.stage in (STAGE_WON, STAGE_LOST):
                company_ids = opportunity.vessel.relationships.values_list(
                    "company_id", flat=True
                )
                if company_ids:
                    from apps.relationships.models import VesselRelationship

                    related_vessel_ids = (
                        VesselRelationship.objects.filter(company_id__in=company_ids)
                        .values_list("vessel_id", flat=True)
                    )
                    other_open = (
                        Opportunity.objects.filter(vessel_id__in=related_vessel_ids)
                        .exclude(pk=opportunity.pk)
                        .exclude(stage__in=CLOSED_STAGES)
                    )
                    for other_opp in other_open:
                        recalculate_score(other_opp)

        return Response(OpportunitySerializer(opportunity).data)


class OpportunityNotesAPIView(APIView):
    """GET and POST notes for an Opportunity. PUT/PATCH/DELETE return 405."""

    permission_classes = [IsAdminOrBDManager]

    def get(self, request, pk):
        opp = get_object_or_404(Opportunity, pk=pk)
        notes_qs = opp.notes.select_related("author").all()

        paginator = StandardResultsSetPagination()
        page = paginator.paginate_queryset(notes_qs, request, view=self)
        if page is not None:
            serializer = OpportunityNoteSerializer(page, many=True)
            return paginator.get_paginated_response(serializer.data)
        serializer = OpportunityNoteSerializer(notes_qs, many=True)
        return Response(serializer.data)

    def post(self, request, pk):
        opp = get_object_or_404(Opportunity, pk=pk)
        raw_text = request.data.get("text")
        if raw_text is None or not str(raw_text).strip():
            return Response(
                {"text": ["This field may not be blank."]},
                status=status.HTTP_400_BAD_REQUEST,
            )
        text = str(raw_text).strip()
        if len(text) > 2000:
            return Response(
                {"text": ["Ensure this field has no more than 2000 characters."]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        note = OpportunityNote.objects.create(
            opportunity=opp,
            author=request.user if request.user.is_authenticated else None,
            text=text,
        )
        return Response(OpportunityNoteSerializer(note).data, status=status.HTTP_201_CREATED)


class OpportunityHistoryAPIView(APIView):
    """GET stage change history for an Opportunity. PUT/PATCH/DELETE return 405."""

    permission_classes = [IsAdminOrBDManager]

    def get(self, request, pk):
        opp = get_object_or_404(Opportunity, pk=pk)
        history_qs = opp.stage_changes.select_related("changed_by").all()

        paginator = StandardResultsSetPagination()
        page = paginator.paginate_queryset(history_qs, request, view=self)
        if page is not None:
            serializer = OpportunityStageChangeSerializer(page, many=True)
            return paginator.get_paginated_response(serializer.data)
        serializer = OpportunityStageChangeSerializer(history_qs, many=True)
        return Response(serializer.data)
