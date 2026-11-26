"""Pages for the Send mail feature: the email templates and the log of mails sent."""
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.generic import TemplateView

from .views import RoleRequiredMixin


@method_decorator(ensure_csrf_cookie, name="dispatch")
class EmailTemplatesPageView(RoleRequiredMixin, TemplateView):
    """Admins and BD Managers write and switch off the email templates here."""

    template_name = "web/email_templates.html"


@method_decorator(ensure_csrf_cookie, name="dispatch")
class EmailLogPageView(RoleRequiredMixin, TemplateView):
    """Every mail sent from the app, newest first."""

    template_name = "web/email_log.html"
