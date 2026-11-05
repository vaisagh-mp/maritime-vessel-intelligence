from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, render
from django.views.generic import TemplateView, View

from apps.common.permissions import is_admin_or_bd_manager
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


class HomeView(RoleRequiredMixin, TemplateView):
    """Lead board home view, protected by login and role."""

    template_name = "web/home.html"


class VesselDetailView(RoleRequiredMixin, View):
    """Vessel detail view, protected by login and role."""

    def get(self, request, pk):
        vessel = get_object_or_404(Vessel, pk=pk)
        return render(request, "web/vessel.html", {"vessel": vessel})


class LeadPlaceholderView(RoleRequiredMixin, TemplateView):
    """Placeholder lead detail page."""

    template_name = "web/lead_placeholder.html"
