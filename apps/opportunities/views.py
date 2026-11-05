import csv
from datetime import datetime, timezone
import io

from django.conf import settings
import django_filters
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponse
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

    zone = django_filters.CharFilter(
        method="filter_zone", label="Arrival zone"
    )
    band = django_filters.CharFilter(
        method="filter_band", label="Priority band (HOT/HIGH/MEDIUM/LOW)"
    )

    class Meta:
        model = Opportunity
        fields = ["stage", "zone", "port", "vessel"]

    def filter_zone(self, queryset, name, value):
        if not value:
            return queryset
        zones = [z.strip() for z in value.split(",") if z.strip()]
        if len(zones) > 1:
            return queryset.filter(zone__in=zones)
        if value == "anchorage":
            return queryset.filter(zone__in=["anchorage", "anchorage_bound"])
        return queryset.filter(zone=value)

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


def sanitize_csv_cell(val):
    """Guard against CSV injection for spreadsheet viewers.
    Any text cell starting with '=', '+', '-', '@', tab, or carriage return
    is written with a leading single quote.
    """
    if val is None:
        return ""
    text = str(val)
    if text and text[0] in ("=", "+", "-", "@", "\t", "\r"):
        return f"'{text}"
    return text


def filter_and_order_opportunities(request):
    """Reusable filtering and ordering logic shared by list and export views."""
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
            return None, Response(
                {"eta_before": ["Invalid ISO datetime format for eta_before."]},
                status=status.HTTP_400_BAD_REQUEST,
            )
        qs = qs.filter(eta__lte=dt_before)

    eta_after = request.query_params.get("eta_after")
    if eta_after:
        dt_after = parse_datetime(eta_after)
        if dt_after is None:
            return None, Response(
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

    return qs, None


class OpportunityListAPIView(APIView):
    """Read-only list for Opportunities with extended search and date filters."""

    permission_classes = [IsAdminOrBDManager]

    def get(self, request):
        qs, error_response = filter_and_order_opportunities(request)
        if error_response:
            return error_response

        paginator = StandardResultsSetPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        if page is not None:
            serializer = OpportunitySerializer(page, many=True)
            return paginator.get_paginated_response(serializer.data)
        serializer = OpportunitySerializer(qs, many=True)
        return Response(serializer.data)


class OpportunityExportAPIView(APIView):
    """GET /api/v1/opportunities/export/ — CSV export of leads with injection protection."""

    permission_classes = [IsAdminOrBDManager]

    def get(self, request):
        qs, error_response = filter_and_order_opportunities(request)
        if error_response:
            return error_response

        cap = getattr(settings, "OPPORTUNITY_EXPORT_CAP", 5000)
        # Fetch cap + 1 in a single query to detect truncation
        rows = list(qs[: cap + 1])
        is_truncated = len(rows) > cap
        if is_truncated:
            rows = rows[:cap]

        buffer = io.StringIO()
        buffer.write("\ufeff")  # UTF-8 BOM
        writer = csv.writer(buffer)

        header = [
            "score",
            "band",
            "zone",
            "stage",
            "vessel_name",
            "imo",
            "mmsi",
            "vessel_type",
            "grt",
            "dwt",
            "flag",
            "port",
            "port_unlocode",
            "eta_utc",
            "eta_source",
            "is_inbound",
            "lead_reason",
            "detected_at_utc",
        ]
        writer.writerow(header)

        for opp in rows:
            v = opp.vessel
            p = opp.port
            eta_str = opp.eta.strftime("%Y-%m-%dT%H:%M:%SZ") if opp.eta else ""
            detected_str = (
                opp.detected_at.strftime("%Y-%m-%dT%H:%M:%SZ")
                if opp.detected_at
                else ""
            )
            row = [
                opp.score,
                sanitize_csv_cell(opp.band),
                sanitize_csv_cell(opp.zone),
                sanitize_csv_cell(opp.stage),
                sanitize_csv_cell(v.name if v else ""),
                sanitize_csv_cell(v.imo or "" if v else ""),
                sanitize_csv_cell(v.mmsi if v else ""),
                sanitize_csv_cell(v.vessel_type or "" if v else ""),
                v.grt if v and v.grt is not None else "",
                v.dwt if v and v.dwt is not None else "",
                sanitize_csv_cell(v.flag or "" if v else ""),
                sanitize_csv_cell(p.name if p else ""),
                sanitize_csv_cell(p.un_locode if p else ""),
                eta_str,
                sanitize_csv_cell(opp.eta_source or ""),
                "yes" if opp.is_inbound else "no",
                sanitize_csv_cell(opp.lead_reason or ""),
                detected_str,
            ]
            writer.writerow(row)

        now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        filename = f"leads_{now_utc}_utc.csv"

        response = HttpResponse(buffer.getvalue(), content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        if is_truncated:
            response["X-Export-Truncated"] = "true"

        return response


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
            opportunity = (
                Opportunity.objects.select_for_update()
                .select_related("vessel", "port")
                .filter(pk=pk)
                .first()
            )
            if not opportunity:
                return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

            if "expected_stage" in request.data:
                expected_stage = request.data.get("expected_stage")
                if expected_stage != opportunity.stage:
                    return Response(
                        {
                            "detail": (
                                "This lead's stage was changed by someone else. "
                                "Reload the page to see the latest stage."
                            )
                        },
                        status=status.HTTP_409_CONFLICT,
                    )

            old_stage = opportunity.stage
            opportunity = serializer.update(opportunity, serializer.validated_data)
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
