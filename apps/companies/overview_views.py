"""
apps/companies/overview_views.py

Read-only API views for the Companies section of the web app.
These are NEW endpoints and do not alter the existing CompanyListCreateAPIView
or CompanyDetailAPIView.
"""

from collections import defaultdict

from django.conf import settings
from django.db.models import (
    Case,
    Count,
    IntegerField,
    Max,
    Q,
    Value,
    When,
)
from rest_framework.exceptions import NotFound
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.constants import CLOSED_STAGES
from apps.common.permissions import IsAdminOrBDManager
from apps.opportunities.models import Opportunity
from apps.relationships.models import VesselRelationship
from services.scoring_service import get_band

from .models import Company


class OverviewPagination(PageNumberPagination):
    page_size = 12
    page_size_query_param = "page_size"
    max_page_size = 200

    def paginate_queryset(self, queryset, request, view=None):
        """A page number past the end (an old bookmark) shows the last page."""
        try:
            return super().paginate_queryset(queryset, request, view)
        except NotFound:
            paginator = self.django_paginator_class(queryset, self.get_page_size(request))
            self.page = paginator.get_page(paginator.num_pages)
            self.request = request
            return list(self.page)


class CompanyOverviewAPIView(APIView):
    """
    GET /api/v1/companies/overview/

    Returns a paginated list of companies with vessel counts, role counts,
    open lead counts, best score/band. Supports filtering and ordering.
    """

    permission_classes = [IsAdminOrBDManager]

    def get(self, request):
        qs = Company.objects.all()

        # --- Filters ---
        q = request.query_params.get("q", "").strip()
        if q:
            qs = qs.filter(name__icontains=q)

        country = request.query_params.get("country", "").strip()
        if country:
            qs = qs.filter(country__iexact=country)

        # Vessel count is annotated BEFORE the role filter below, so choosing a
        # role never shrinks the total shown on the card.
        qs = qs.annotate(
            vessel_count=Count(
                "vessel_relationships__vessel",
                filter=Q(vessel_relationships__is_current=True),
                distinct=True,
            )
        )

        company_type = request.query_params.get("type", "").strip()
        if company_type:
            qs = qs.filter(company_type=company_type)

        # Role filter: only companies that have at least one current
        # relationship with that role.
        role_filter = request.query_params.get("role", "").strip()
        if role_filter:
            qs = qs.filter(
                vessel_relationships__role=role_filter,
                vessel_relationships__is_current=True,
            ).distinct()

        # has_open_leads: only companies linked to vessels with open leads.
        has_open_leads = request.query_params.get("has_open_leads", "").strip().lower()

        # --- Gather role counts, open leads, best score per company ---
        # We do this in a small number of grouped queries rather than N+1.
        company_ids = list(qs.values_list("id", flat=True))

        # 1. Role counts per company (only current relationships)
        role_counts_rows = (
            VesselRelationship.objects.filter(
                company_id__in=company_ids, is_current=True
            )
            .values("company_id", "role")
            .annotate(n=Count("vessel_id", distinct=True))
        )
        role_counts_map = defaultdict(dict)  # {company_id: {role: n}}
        for row in role_counts_rows:
            role_counts_map[row["company_id"]][row["role"]] = row["n"]

        # 2. Open leads per company: count of open Opportunities on vessels
        #    currently linked to each company.
        open_lead_rows = (
            Opportunity.objects.filter(
                vessel__relationships__company_id__in=company_ids,
                vessel__relationships__is_current=True,
            )
            .exclude(stage__in=CLOSED_STAGES)
            .values("vessel__relationships__company_id")
            .annotate(
                open_leads=Count("id", distinct=True),
                best_score=Max("score"),
            )
        )
        open_lead_map = {}  # {company_id: {open_leads, best_score}}
        for row in open_lead_rows:
            cid = row["vessel__relationships__company_id"]
            existing = open_lead_map.get(cid)
            if existing is None or row["best_score"] > existing["best_score"]:
                open_lead_map[cid] = {
                    "open_leads": row["open_leads"],
                    "best_score": row["best_score"],
                }

        # --- has_open_leads filter (after we have the data) ---
        if has_open_leads == "true":
            company_ids_with_leads = set(open_lead_map.keys())
            qs = qs.filter(id__in=company_ids_with_leads)

        # --- Ordering ---
        ordering = request.query_params.get("ordering", "name").strip()
        if ordering == "vessels":
            qs = qs.order_by("vessel_count", "name")
        elif ordering == "-vessels":
            qs = qs.order_by("-vessel_count", "name")
        elif ordering == "hottest":
            # Sort by best_score descending, done in Python after pagination
            # since best_score is not an annotation on Company queryset.
            # We annotate a proxy for ordering.
            qs = _annotate_best_score(qs, open_lead_map)
            qs = qs.order_by("-_best_score", "name")
        else:
            qs = qs.order_by("name")

        # --- Paginate ---
        paginator = OverviewPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        items = page if page is not None else list(qs)

        results = []
        for company in items:
            cid = company.id
            leads = open_lead_map.get(cid, {"open_leads": 0, "best_score": 0})
            best_score = leads.get("best_score") or 0
            results.append(
                {
                    "id": cid,
                    "name": company.name,
                    "company_type": company.company_type,
                    "country": company.country,
                    "website": company.website,
                    "email": company.email,
                    "vessel_count": company.vessel_count,
                    "role_counts": role_counts_map.get(cid, {}),
                    "open_leads": leads.get("open_leads", 0),
                    "best_band": get_band(best_score) if best_score else "LOW",
                    "best_score": best_score,
                }
            )

        if page is not None:
            return paginator.get_paginated_response(results)
        return Response(results)


def _annotate_best_score(qs, open_lead_map):
    """Add a _best_score annotation from the precomputed map using Case/When."""
    whens = []
    for cid, data in open_lead_map.items():
        whens.append(When(id=cid, then=Value(data.get("best_score", 0))))
    if whens:
        qs = qs.annotate(
            _best_score=Case(*whens, default=Value(0), output_field=IntegerField())
        )
    else:
        qs = qs.annotate(_best_score=Value(0, output_field=IntegerField()))
    return qs


class CompanyVesselsAPIView(APIView):
    """
    GET /api/v1/companies/<id>/vessels/

    Returns paginated list of vessels linked to this company (current
    relationships only), with each vessel's role(s), verified flag, and
    open lead if any.
    """

    permission_classes = [IsAdminOrBDManager]

    def get(self, request, pk):
        from django.shortcuts import get_object_or_404

        company = get_object_or_404(Company, pk=pk)

        # Relationships for this company (current only)
        rels_qs = VesselRelationship.objects.filter(
            company=company, is_current=True
        ).select_related("vessel")

        role_filter = request.query_params.get("role", "").strip()
        if role_filter:
            rels_qs = rels_qs.filter(role=role_filter)

        # Group by vessel
        vessel_map = {}  # vessel_id -> {vessel, roles, verified}
        for rel in rels_qs:
            v = rel.vessel
            if v.id not in vessel_map:
                vessel_map[v.id] = {
                    "vessel": v,
                    "roles": [],
                    "verified": False,
                }
            vessel_map[v.id]["roles"].append(rel.role)
            if rel.verified:
                vessel_map[v.id]["verified"] = True

        vessel_ids = list(vessel_map.keys())

        # Open leads per vessel (best one, by score desc)
        open_leads = {}
        if vessel_ids:
            leads_qs = (
                Opportunity.objects.filter(vessel_id__in=vessel_ids)
                .exclude(stage__in=CLOSED_STAGES)
                .select_related("port")
                .order_by("-score")
            )
            for lead in leads_qs:
                if lead.vessel_id not in open_leads:
                    open_leads[lead.vessel_id] = lead

        # Build result list (sorted by vessel name)
        rows = sorted(vessel_map.values(), key=lambda v: v["vessel"].name)

        # Paginate
        paginator = OverviewPagination()
        paginator.page_size = 25

        # Manual pagination over the list
        from django.core.paginator import Paginator as DjangoPaginator

        page_number = request.query_params.get(paginator.page_query_param, 1)
        page_size = request.query_params.get(
            paginator.page_size_query_param, paginator.page_size
        )
        try:
            page_size = min(int(page_size), paginator.max_page_size)
        except (ValueError, TypeError):
            page_size = paginator.page_size
        try:
            page_number = max(int(page_number), 1)
        except (ValueError, TypeError):
            page_number = 1

        django_paginator = DjangoPaginator(rows, page_size)
        page_obj = django_paginator.get_page(page_number)

        results = []
        for entry in page_obj:
            v = entry["vessel"]
            lead = open_leads.get(v.id)
            lead_data = None
            if lead:
                lead_data = {
                    "id": lead.id,
                    "port": lead.port.name if lead.port else None,
                    "eta": lead.eta.isoformat() if lead.eta else None,
                    "band": get_band(lead.score),
                    "score": lead.score,
                    "stage": lead.stage,
                    "is_inbound": lead.is_inbound,
                }
            results.append(
                {
                    "id": v.id,
                    "name": v.name,
                    "imo": v.imo,
                    "mmsi": v.mmsi,
                    "vessel_type": v.vessel_type,
                    "grt": v.grt,
                    "flag": v.flag,
                    "roles": entry["roles"],
                    "verified": entry["verified"],
                    "open_lead": lead_data,
                }
            )

        return Response(
            {
                "count": django_paginator.count,
                "results": results,
            }
        )
