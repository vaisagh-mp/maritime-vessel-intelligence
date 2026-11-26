from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.generic import TemplateView, View

from apps.common.permissions import is_admin, is_admin_or_bd_manager
from apps.opportunities.models import Opportunity
from apps.vessels.models import Vessel


class RoleRequiredMixin(LoginRequiredMixin):
    """Requires authentication AND an active role (admin or bd_manager).
    Signed-in users with no role receive HTTP 403 with no_access.html.
    Anonymous users are redirected to login.
    """

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not is_admin_or_bd_manager(request.user):
            return render(request, "web/no_access.html", status=403)
        return super().dispatch(request, *args, **kwargs)


class AdminRequiredMixin(LoginRequiredMixin):
    """Admin only. Anonymous users go to login; BD Managers see a 403 page."""

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not is_admin(request.user):
            if is_admin_or_bd_manager(request.user):
                return render(request, "web/no_access.html", {"admin_only": True}, status=403)
            return render(request, "web/no_access.html", status=403)
        return super().dispatch(request, *args, **kwargs)


PRIORITY_PAGES = {
    "all": {
        "title": "All leads",
        "blurb": "Every open lead in every zone, highest score first.",
        "empty": "No leads for these filters.",
    },
    "24h": {
        "title": "24 hour priority",
        "blurb": "Vessels expected within the next 24 hours, highest score first.",
        "empty": "No leads in the 24 hour window for these filters.",
    },
    "72h": {
        "title": "72 hour approach",
        "blurb": "Vessels expected in 24 to 72 hours.",
        "empty": "No leads in the 72 hour window for these filters.",
    },
    "anchorage": {
        "title": "Anchorage / port",
        "blurb": "Vessels waiting at anchor or already in port.",
        "empty": "No leads at anchorage or in port for these filters.",
    },
}


@method_decorator(ensure_csrf_cookie, name="dispatch")
class HomeView(RoleRequiredMixin, TemplateView):
    """Dashboard: welcome, summary cards, hot leads table and side panels."""

    template_name = "web/dashboard.html"


@method_decorator(ensure_csrf_cookie, name="dispatch")
class PriorityView(RoleRequiredMixin, View):
    """One priority list (24 hour, 72 hour or anchorage) as a table."""

    def get(self, request, zone):
        page = PRIORITY_PAGES.get(zone)
        if page is None:
            raise Http404("Unknown priority list")
        if zone == "anchorage" and not getattr(settings, "INGEST_REFRESH_AIS_ENABLED", True):
            raise Http404("Anchorage list is switched off")
        return render(request, "web/priority.html", {"zone": zone, "page": page})


@method_decorator(ensure_csrf_cookie, name="dispatch")
class LatestArrivalsView(RoleRequiredMixin, View):
    """Vessels from the last live arrivals fetch of each port, with owners and managers."""

    def get(self, request):
        from apps.ports.models import Port

        ports = Port.objects.filter(active=True, marinetraffic_port_id__isnull=False).order_by("name")
        return render(request, "web/latest.html", {"ports": ports})


class PriorityIndexView(RoleRequiredMixin, View):
    def get(self, request):
        return redirect("web:priority", zone="24h")


@method_decorator(ensure_csrf_cookie, name="dispatch")
class BusinessDevelopersView(AdminRequiredMixin, TemplateView):
    """Admin page to add Business Developers and manage their accounts."""

    template_name = "web/business_developers.html"


@method_decorator(ensure_csrf_cookie, name="dispatch")
class VesselDetailView(RoleRequiredMixin, View):
    """Vessel detail view, protected by login and role."""

    def get(self, request, pk):
        vessel = get_object_or_404(Vessel, pk=pk)
        return render(request, "web/vessel.html", {"vessel": vessel})


@method_decorator(ensure_csrf_cookie, name="dispatch")
class LeadDetailView(RoleRequiredMixin, View):
    """Lead detail and pipeline view, protected by login and role."""

    def get(self, request, pk):
        opportunity = get_object_or_404(
            Opportunity.objects.select_related("vessel", "port"), pk=pk
        )
        return render(request, "web/lead.html", {"opportunity": opportunity})
