"""
apps/web/company_views.py

Web views for the Companies section: list page and detail page.
"""

from django.shortcuts import get_object_or_404, render
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views import View

from apps.companies.models import Company

from .views import RoleRequiredMixin


@method_decorator(ensure_csrf_cookie, name="dispatch")
class CompanyListPageView(RoleRequiredMixin, View):
    """Company list page — /companies/."""

    def get(self, request):
        return render(request, "web/companies.html")


@method_decorator(ensure_csrf_cookie, name="dispatch")
class CompanyDetailPageView(RoleRequiredMixin, View):
    """Company detail page — /companies/<id>/."""

    def get(self, request, pk):
        company = get_object_or_404(Company, pk=pk)
        return render(request, "web/company.html", {"company": company})
