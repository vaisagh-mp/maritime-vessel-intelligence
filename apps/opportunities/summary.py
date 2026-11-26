"""Dashboard summary: counts and short lists for the web Dashboard, in one request.

GET /api/v1/opportunities/summary/?port=<id>   (port optional)
"""
from datetime import timedelta

from django.db.models import Q

from django.conf import settings
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.constants import (
    CLOSED_STAGES,
    OPPORTUNITY_STAGE_CHOICES,
    STAGE_CONTACTED,
    STAGE_DETECTED,
    STAGE_NEGOTIATION,
    STAGE_QUOTE_REQUESTED,
    STALE_INBOUND_HIDE_HOURS,
    STAGE_QUOTED,
    STAGE_REPLIED,
    STAGE_WON,
)
from apps.common.permissions import IsAdminOrBDManager
from apps.ports.models import Port

from .models import Opportunity, OpportunityStageChange

PIPELINE_STAGES = [STAGE_CONTACTED, STAGE_REPLIED, STAGE_QUOTE_REQUESTED, STAGE_QUOTED, STAGE_NEGOTIATION]
STAGE_LABELS = dict(OPPORTUNITY_STAGE_CHOICES)
ATTENTION_AFTER_HOURS = 24
ATTENTION_LIMIT = 6
ACTIVITY_LIMIT = 8


def _threshold(label):
    for score, name in settings.SCORE_BANDS:
        if name == label:
            return score
    return 0


class DashboardSummaryAPIView(APIView):
    permission_classes = [IsAdminOrBDManager]

    def get(self, request):
        port_param = (request.query_params.get("port") or "").strip()
        base = Opportunity.objects.select_related("vessel", "port")
        if port_param.isdigit():
            base = base.filter(port_id=int(port_param))

        now = timezone.now()
        open_qs = base.exclude(stage__in=CLOSED_STAGES)
        hot_min = _threshold("HOT")
        high_min = _threshold("HIGH")

        fresh = open_qs.exclude(is_inbound=True, eta__lt=now - timedelta(hours=STALE_INBOUND_HIDE_HOURS))

        totals = {
            "open": open_qs.count(),
            "hot": open_qs.filter(score__gte=hot_min).count(),
            "inbound": open_qs.filter(is_inbound=True).filter(Q(eta__isnull=True) | Q(eta__gte=now)).count(),
            "zone_24h": fresh.filter(zone="24h").count(),
            "zone_72h": fresh.filter(zone="72h").count(),
            "anchorage": open_qs.filter(zone__in=["anchorage", "anchorage_bound"]).count(),
            "in_pipeline": open_qs.filter(stage__in=PIPELINE_STAGES).count(),
            "new_24h": open_qs.filter(detected_at__gte=now - timedelta(hours=24)).count(),
            "won": base.filter(stage=STAGE_WON).count(),
        }

        stage_counts = {s: 0 for s, _ in OPPORTUNITY_STAGE_CHOICES}
        for row in open_qs.values_list("stage", flat=True):
            stage_counts[row] = stage_counts.get(row, 0) + 1
        by_stage = [
            {"stage": s, "label": STAGE_LABELS[s], "count": stage_counts.get(s, 0)}
            for s, _ in OPPORTUNITY_STAGE_CHOICES
            if s not in CLOSED_STAGES
        ]

        by_port = []
        port_rows = Port.objects.filter(active=True).order_by("name")
        for port in port_rows:
            qs = Opportunity.objects.filter(port=port).exclude(stage__in=CLOSED_STAGES)
            by_port.append({
                "port_id": port.id,
                "name": port.name,
                "un_locode": port.un_locode,
                "open": qs.count(),
                "hot": qs.filter(score__gte=hot_min).count(),
            })

        attention_qs = open_qs.filter(
            stage=STAGE_DETECTED,
            score__gte=high_min,
            detected_at__lte=now - timedelta(hours=ATTENTION_AFTER_HOURS),
        ).order_by("-score")
        attention = []
        for opp in attention_qs[:ATTENTION_LIMIT]:
            attention.append({
                "id": opp.id,
                "vessel_name": opp.vessel.name,
                "band": opp.band,
                "score": opp.score,
                "port": opp.port.un_locode or opp.port.name,
                "hours_waiting": int((now - opp.detected_at).total_seconds() // 3600),
            })

        changes = OpportunityStageChange.objects.select_related(
            "opportunity__vessel", "changed_by"
        ).order_by("-changed_at")
        if port_param.isdigit():
            changes = changes.filter(opportunity__port_id=int(port_param))
        activity = []
        for ch in changes[:ACTIVITY_LIMIT]:
            who = ""
            if ch.changed_by_id:
                who = ch.changed_by.get_full_name() or ch.changed_by.get_username()
            activity.append({
                "opportunity_id": ch.opportunity_id,
                "vessel_name": ch.opportunity.vessel.name,
                "from_label": STAGE_LABELS.get(ch.from_stage, ch.from_stage or "New"),
                "to_label": STAGE_LABELS.get(ch.to_stage, ch.to_stage),
                "by": who or "System",
                "at": ch.changed_at.isoformat(),
            })

        from apps.enrichment.models import IngestRun

        last_refresh = []
        for port in port_rows:
            run = (
                IngestRun.objects.filter(port_code=port.un_locode)
                .exclude(status=IngestRun.STATUS_RUNNING)
                .first()
            )
            last_refresh.append({
                "port": port.un_locode,
                "name": port.name,
                "status": run.status if run else None,
                "finished_at": run.finished_at.isoformat() if run and run.finished_at else None,
            })

        return Response({
            "totals": totals,
            "by_stage": by_stage,
            "by_port": by_port,
            "needs_attention": {
                "count": attention_qs.count(),
                "after_hours": ATTENTION_AFTER_HOURS,
                "items": attention,
            },
            "recent_activity": activity,
            "last_refresh": last_refresh,
        })
