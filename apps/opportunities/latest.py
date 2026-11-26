"""
GET /api/v1/opportunities/latest-arrivals/?date=YYYY-MM-DD&port=<id or code>&band=HOT&page=1

The vessels saved by the live Expected Arrivals fetch of each port on one UTC day (default:
today), with their owners and managers. Read-only.

Fetches made since the history table exists are read from it exactly. A fetch from before
that is rebuilt from the leads saved shortly after its EnrichmentLog row; later fetches
overwrite those, so such a day can be incomplete (the reply says ``approximate``).
"""
from datetime import date as date_type, datetime, timedelta, timezone as dt_timezone

from django.core.paginator import Paginator
from django.db.models.functions import TruncDate
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.constants import RELATIONSHIP_ROLE_CHOICES
from apps.common.permissions import IsAdminOrBDManager
from apps.enrichment.models import ArrivalsFetch, EnrichmentLog
from apps.opportunities.models import Opportunity
from apps.ports.models import Port
from apps.relationships.models import VesselRelationship
from services import quota_service
from services.scoring_service import get_band

BEFORE = timedelta(minutes=1)
AFTER = timedelta(minutes=30)
ROLE_LABELS = dict(RELATIONSHIP_ROLE_CHOICES)
OWNER_ROLES = {"registered_owner", "beneficial_owner", "owner"}
HISTORY_DAYS = 60


def _ports(param):
    qs = Port.objects.filter(active=True, marinetraffic_port_id__isnull=False).order_by("un_locode")
    param = (param or "").strip()
    if param.isdigit():
        qs = qs.filter(pk=int(param))
    elif param:
        qs = qs.filter(un_locode__iexact=param)
    return list(qs)


def _day(param):
    """(day, start, end) in UTC. A missing or bad value means today."""
    today = timezone.now().astimezone(dt_timezone.utc).date()
    try:
        day = date_type.fromisoformat((param or "").strip()) if param else today
    except ValueError:
        day = today
    start = datetime(day.year, day.month, day.day, tzinfo=dt_timezone.utc)
    return day, start, start + timedelta(days=1)


def _row(vessel, port_code, opp, eta, zone, score):
    return {
        "opp": opp, "vessel": vessel, "port": port_code, "eta": eta, "zone": zone, "score": score,
        "stage": opp.stage if opp else "", "is_inbound": opp.is_inbound if opp else False,
    }


def _fetch_for_day(port, start, end):
    """(fetched_at, rows, approximate) of the day's latest fetch of a port, or None."""
    rec = ArrivalsFetch.objects.filter(port=port, fetched_at__gte=start, fetched_at__lt=end).order_by("-fetched_at").first()
    if rec:
        items = rec.items.select_related("vessel", "opportunity")
        return rec.fetched_at, [_row(i.vessel, port.un_locode, i.opportunity, i.eta, i.zone, i.score) for i in items], False
    logs = EnrichmentLog.objects.filter(
        port=port, success=True, endpoint_called=quota_service.ARRIVALS_ENDPOINT,
        timestamp__gte=start, timestamp__lt=end,
    ).order_by("-timestamp")
    log = logs.first()
    if not log:
        return None
    t = log.timestamp
    nxt = (EnrichmentLog.objects.filter(
        port=port, success=True, endpoint_called=quota_service.ARRIVALS_ENDPOINT, timestamp__gt=t,
    ).order_by("timestamp").first())
    upper = min(t + AFTER, nxt.timestamp - BEFORE) if nxt else t + AFTER
    opps = Opportunity.objects.filter(port=port, updated_at__gte=t - BEFORE, updated_at__lte=upper).select_related("vessel")
    return t, [_row(o.vessel, port.un_locode, o, o.eta, o.zone, o.score) for o in opps], True


def _dates_with_fetches(ports):
    ids = [p.pk for p in ports]
    seen = set()
    for model, field in ((ArrivalsFetch, "fetched_at"),):
        for d in model.objects.filter(port_id__in=ids).annotate(d=TruncDate(field)).values_list("d", flat=True).distinct():
            seen.add(d)
    for d in (EnrichmentLog.objects.filter(port_id__in=ids, success=True, endpoint_called=quota_service.ARRIVALS_ENDPOINT)
              .annotate(d=TruncDate("timestamp")).values_list("d", flat=True).distinct()):
        seen.add(d)
    return [d.isoformat() for d in sorted(seen, reverse=True)[:HISTORY_DAYS] if d]


class LatestArrivalsAPIView(APIView):
    permission_classes = [IsAdminOrBDManager]

    def get(self, request):
        ports = _ports(request.query_params.get("port"))
        band_filter = (request.query_params.get("band") or "").strip().upper()
        day, start, end = _day(request.query_params.get("date"))

        summaries, rows = [], []
        for port in ports:
            found = _fetch_for_day(port, start, end)
            if found is None:
                summaries.append({"port": port.un_locode, "name": port.name, "fetched_at": None,
                                  "vessels": 0, "with_owner": 0, "with_manager": 0, "approximate": False})
                continue
            fetched_at, port_rows, approx = found
            owner_ids, manager_ids = set(), set()
            vids = [r["vessel"].pk for r in port_rows]
            for vid, role in VesselRelationship.objects.filter(vessel_id__in=vids, is_current=True).values_list("vessel_id", "role"):
                (owner_ids if role in OWNER_ROLES else manager_ids).add(vid)
            summaries.append({
                "port": port.un_locode, "name": port.name, "fetched_at": fetched_at.isoformat(),
                "vessels": len(port_rows), "with_owner": len(owner_ids), "with_manager": len(manager_ids),
                "approximate": approx,
            })
            rows.extend(port_rows)

        if band_filter:
            rows = [r for r in rows if get_band(r["score"]) == band_filter]
        rows.sort(key=lambda r: (-r["score"], r["vessel"].name))

        try:
            size = min(max(int(request.query_params.get("page_size", 25)), 1), 100)
        except (TypeError, ValueError):
            size = 25
        page = Paginator(rows, size).get_page(request.query_params.get("page", 1))

        vessel_ids = [r["vessel"].pk for r in page]
        by_vessel = {vid: [] for vid in vessel_ids}
        rels = (VesselRelationship.objects.filter(vessel_id__in=vessel_ids, is_current=True)
                .select_related("company").order_by("role", "company__name"))
        for rel in rels:
            c = rel.company
            by_vessel[rel.vessel_id].append({
                "role": rel.role, "role_label": ROLE_LABELS.get(rel.role, rel.role),
                "group": "owner" if rel.role in OWNER_ROLES else "manager",
                "company_id": c.id, "name": c.name, "country": c.country, "email": c.email,
                "website": c.website, "verified": rel.verified,
            })

        results = []
        for r in page:
            v = r["vessel"]
            results.append({
                "id": r["opp"].id if r["opp"] else None,
                "port": r["port"],
                "eta": r["eta"].isoformat() if r["eta"] else None,
                "zone": r["zone"], "score": r["score"], "band": get_band(r["score"]),
                "stage": r["stage"], "is_inbound": r["is_inbound"],
                "vessel": {
                    "id": v.id, "name": v.name, "imo": v.imo, "vessel_type": v.vessel_type,
                    "grt": v.grt, "flag": v.flag,
                    "ownership_checked_at": v.ownership_checked_at.isoformat() if v.ownership_checked_at else None,
                },
                "companies": by_vessel.get(v.id, []),
            })

        return Response({
            "date": day.isoformat(),
            "dates": _dates_with_fetches(ports),
            "fetches": summaries,
            "count": page.paginator.count,
            "page": page.number,
            "pages": page.paginator.num_pages,
            "results": results,
        })
