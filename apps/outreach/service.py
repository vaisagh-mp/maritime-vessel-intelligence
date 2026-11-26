"""Rendering and sending for the "Send mail" button. No mail leaves the app without a person pressing Send."""
import re
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.mail import EmailMessage
from django.core.validators import validate_email
from django.utils import timezone

from apps.common.constants import CLOSED_STAGES
from apps.opportunities.models import Opportunity

from .models import EmailLog

PLACEHOLDER = re.compile(r"\{\{\s*([a-z_]+)\s*\}\}")
KNOWN = {
    "company_name", "vessel_name", "imo", "vessel_type", "grt", "flag", "port", "eta", "role",
    "sender_name", "sender_first_name",
}
# Addresses that are rarely the right person to mail about a vessel.
GENERIC_PREFIXES = ("hr", "career", "careers", "job", "jobs", "recruit", "recruitment", "noreply", "no-reply", "donotreply")
PLACEHOLDER_NAMES = ["company_name", "vessel_name", "imo", "vessel_type", "grt", "flag", "port", "eta",
                      "role", "sender_name", "sender_first_name"]
MAX_SUBJECT = 200
MAX_BODY = 20000


def mode() -> str:
    """"live" when an SMTP server is configured, otherwise "test" (printed in the server window)."""
    return "live" if getattr(settings, "EMAIL_HOST", "") else "test"


def enabled() -> bool:
    return bool(getattr(settings, "OUTREACH_ENABLED", True))


def best_opportunity(vessel):
    return (
        Opportunity.objects.filter(vessel=vessel).exclude(stage__in=CLOSED_STAGES)
        .select_related("port").order_by("-score").first()
    )


def _eta_text(opp):
    if not opp or not opp.eta:
        return "to be confirmed"
    return opp.eta.strftime("%d %b %Y %H:%M UTC")


def sender_name(user):
    return (user.get_full_name() or "").strip() or user.get_username()


def build_context(rel, user):
    vessel, company = rel.vessel, rel.company
    opp = best_opportunity(vessel)
    return {
        "company_name": company.name,
        "vessel_name": vessel.name,
        "imo": vessel.imo or "",
        "vessel_type": vessel.vessel_type or "",
        "grt": f"{vessel.grt:,.0f}" if vessel.grt else "",
        "flag": vessel.flag or "",
        "port": opp.port.name if opp and opp.port else "",
        "eta": _eta_text(opp),
        "role": rel.get_role_display(),
        "sender_name": sender_name(user),
        "sender_first_name": (user.first_name or sender_name(user)).strip(),
    }


def render(text, context):
    """(rendered text, sorted unknown placeholder names). Unknown placeholders are left as typed."""
    unknown = set()

    def sub(match):
        key = match.group(1)
        if key in KNOWN:
            return str(context.get(key, ""))
        unknown.add(key)
        return match.group(0)

    return PLACEHOLDER.sub(sub, text or ""), sorted(unknown)


def clean_subject(text):
    """One line only: line breaks in a subject would let extra mail headers be injected."""
    return " ".join((text or "").split())


def valid_address(address):
    address = (address or "").strip()
    if not address or "\n" in address or "\r" in address or "," in address or ";" in address or " " in address:
        return None
    try:
        validate_email(address)
    except ValidationError:
        return None
    return address


def warnings_for(rel, address):
    out = []
    local = address.split("@", 1)[0].lower()
    if local.rstrip("0123456789") in GENERIC_PREFIXES or local in GENERIC_PREFIXES:
        out.append(f"{address} looks like a general or HR mailbox, not a chartering or technical contact.")
    days = int(getattr(settings, "OUTREACH_RESEND_BLOCK_DAYS", 3))
    last = (
        EmailLog.objects.filter(company=rel.company, vessel=rel.vessel, status__in=[EmailLog.STATUS_SENT, EmailLog.STATUS_TEST])
        .filter(sent_at__gte=timezone.now() - timedelta(days=days)).order_by("-sent_at").first()
    )
    if last:
        out.append(f"This company was already mailed about this vessel on {last.sent_at:%d %b %Y} ({last.subject}).")
    return out


def sent_today_by(user):
    start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
    return EmailLog.objects.filter(sent_by=user, sent_at__gte=start).exclude(status=EmailLog.STATUS_FAILED).count()


def test_recipient():
    """The safe-test address (OUTREACH_TEST_RECIPIENT), or "" when real companies are mailed."""
    return valid_address(getattr(settings, "OUTREACH_TEST_RECIPIENT", "")) or ""


def bcc_list():
    raw = getattr(settings, "OUTREACH_BCC", "") or ""
    return [a.strip() for a in raw.split(",") if valid_address(a)]


def deliver(rel, user, subject, body, template=None):
    """Send one mail and record it. Returns the EmailLog row (status sent, test or failed)."""
    address = valid_address(rel.company.email)
    log = EmailLog(
        company=rel.company, vessel=rel.vessel, opportunity=best_opportunity(rel.vessel), relationship=rel,
        template=template, template_name=template.name if template else "", to_email=address or rel.company.email or "",
        subject=subject, body=body, sent_by=user,
    )
    redirect = test_recipient()
    if redirect:
        # Safe test: nothing reaches the company. The subject and the log show who it was meant for.
        subject = f"[TEST for {address}] {subject}"[:MAX_SUBJECT]
        log.subject, log.to_email = subject, redirect
    message = EmailMessage(subject=subject, body=body, to=[redirect or address], bcc=[] if redirect else bcc_list(),
                           reply_to=[user.email] if user.email else None)
    try:
        message.send(fail_silently=False)
        log.status = EmailLog.STATUS_SENT if mode() == "live" else EmailLog.STATUS_TEST
    except Exception as exc:  # noqa: BLE001 - recorded, never raised to the page as a stack trace
        log.status = EmailLog.STATUS_FAILED
        text = str(exc)
        password = getattr(settings, "EMAIL_HOST_PASSWORD", "")
        if password:
            text = text.replace(password, "***")
        log.error = text[:300]
    log.save()
    return log
