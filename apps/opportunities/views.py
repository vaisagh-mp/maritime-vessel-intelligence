import django_filters
from rest_framework import filters as drf_filters
from rest_framework import mixins, viewsets

from apps.common.constants import CLOSED_STAGES, STAGE_LOST, STAGE_WON
from apps.common.permissions import IsAdminOrBDManager
from services.opportunity_service import recalculate_score

from .models import Opportunity
from .serializers import OpportunitySerializer, OpportunityStageUpdateSerializer


class OpportunityBandFilter(django_filters.FilterSet):
    """Custom filterset that adds a `band` query parameter alongside the
    existing stage/zone/port/vessel filters.  Since `band` is not a stored
    column, we translate it into score-range lookups against SCORE_BANDS."""

    band = django_filters.CharFilter(method="filter_band", label="Priority band (HOT/HIGH/MEDIUM/LOW)")

    class Meta:
        model = Opportunity
        fields = ["stage", "zone", "port", "vessel"]

    def filter_band(self, queryset, name, value):
        from django.conf import settings

        value_upper = value.upper()
        bands = settings.SCORE_BANDS  # [(80, "HOT"), (60, "HIGH"), ...]

        for i, (threshold, label) in enumerate(bands):
            if label == value_upper:
                # Upper bound is the previous band's threshold (or no upper bound for the first).
                upper = bands[i - 1][0] if i > 0 else None
                if upper is not None:
                    return queryset.filter(score__gte=threshold, score__lt=upper)
                return queryset.filter(score__gte=threshold)

        return queryset.none()  # Invalid band value


class OpportunityViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """Read-only except for PATCH, which is restricted to updating `stage` —
    everything else about an Opportunity is system-managed. PUT is excluded
    via http_method_names so only partial (stage-only) updates are possible
    (results in 405, not a permission failure).
    """

    queryset = Opportunity.objects.select_related("vessel", "port").all()
    permission_classes = [IsAdminOrBDManager]
    filterset_class = OpportunityBandFilter
    filter_backends = [
        django_filters.rest_framework.DjangoFilterBackend,
        drf_filters.OrderingFilter,
    ]
    ordering_fields = ["score", "detected_at", "eta"]
    ordering = ["-score"]  # default ordering
    http_method_names = ["get", "patch", "head", "options"]

    def get_serializer_class(self):
        if self.request.method == "PATCH":
            return OpportunityStageUpdateSerializer
        return OpportunitySerializer

    def perform_update(self, serializer):
        """After a stage change, recalculate this opportunity's score.
        If the stage moved to won/lost, also cascade-rescore other open
        Opportunities tied to the same vessel's companies (their
        existing-relationship and recent-negative signals just changed)."""
        opportunity = serializer.save()
        recalculate_score(opportunity)

        if opportunity.stage in (STAGE_WON, STAGE_LOST):
            # Find companies linked to this vessel.
            company_ids = opportunity.vessel.relationships.values_list(
                "company_id", flat=True
            )
            if company_ids:
                from apps.relationships.models import VesselRelationship

                related_vessel_ids = (
                    VesselRelationship.objects
                    .filter(company_id__in=company_ids)
                    .values_list("vessel_id", flat=True)
                )
                other_open = (
                    Opportunity.objects
                    .filter(vessel_id__in=related_vessel_ids)
                    .exclude(pk=opportunity.pk)
                    .exclude(stage__in=CLOSED_STAGES)
                )
                for opp in other_open:
                    recalculate_score(opp)
