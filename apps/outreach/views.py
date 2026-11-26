from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.permissions import IsAdminOrBDManager
from apps.relationships.models import VesselRelationship

from . import service
from .models import EmailLog, EmailTemplate


def _template_row(t):
    return {"id": t.id, "name": t.name, "kind": t.kind, "kind_label": t.get_kind_display(),
            "subject": t.subject, "body": t.body}


def _log_row(log):
    return {
        "id": log.id,
        "company_id": log.company_id,
        "vessel_id": log.vessel_id,
        "sent_at": log.sent_at.isoformat(),
        "sent_by": service.sender_name(log.sent_by) if log.sent_by else "",
        "subject": log.subject,
        "template": log.template_name,
        "status": log.status,
    }


def _relationship(request):
    try:
        rel_id = int(request.data.get("relationship_id"))
    except (TypeError, ValueError):
        return None, Response({"detail": "relationship_id is required."}, status=400)
    rel = get_object_or_404(VesselRelationship.objects.select_related("company", "vessel"), pk=rel_id)
    return rel, None


class TemplateListView(APIView):
    permission_classes = [IsAdminOrBDManager]

    def get(self, request):
        rows = EmailTemplate.objects.filter(active=True)
        return Response({
            "mode": service.mode(), "enabled": service.enabled(), "redirect_to": service.test_recipient(),
            "templates": [_template_row(t) for t in rows],
        })


class PreviewView(APIView):
    """POST {relationship_id, template_id}: the mail filled in for this vessel and company. Sends nothing."""

    permission_classes = [IsAdminOrBDManager]

    def post(self, request):
        rel, error = _relationship(request)
        if error:
            return error
        template = get_object_or_404(EmailTemplate, pk=request.data.get("template_id"), active=True)
        context = service.build_context(rel, request.user)
        subject, unknown_s = service.render(template.subject, context)
        body, unknown_b = service.render(template.body, context)
        address = service.valid_address(rel.company.email)
        reason = ""
        if not service.enabled():
            reason = "Sending mail is switched off."
        elif not address:
            reason = "This company has no valid email address."
        return Response({
            "to": address or "",
            "subject": service.clean_subject(subject),
            "body": body,
            "unknown_placeholders": sorted(set(unknown_s) | set(unknown_b)),
            "warnings": service.warnings_for(rel, address) if address else [],
            "mode": service.mode(), "redirect_to": service.test_recipient(),
            "can_send": not reason,
            "reason": reason,
        })


class SendView(APIView):
    """POST {relationship_id, template_id?, subject, body, confirm?}: send ONE mail, as written on screen."""

    permission_classes = [IsAdminOrBDManager]

    def post(self, request):
        if not service.enabled():
            return Response({"detail": "Sending mail is switched off."}, status=status.HTTP_409_CONFLICT)
        rel, error = _relationship(request)
        if error:
            return error
        address = service.valid_address(rel.company.email)
        if not address:
            return Response({"detail": "This company has no valid email address."}, status=400)
        subject = service.clean_subject(request.data.get("subject"))
        body = (request.data.get("body") or "").replace("\r\n", "\n").strip()
        if not subject or not body:
            return Response({"detail": "A subject and a message are both needed."}, status=400)
        if len(subject) > service.MAX_SUBJECT or len(body) > service.MAX_BODY:
            return Response({"detail": "The subject or message is too long."}, status=400)
        if service.PLACEHOLDER.search(subject + body):
            left = sorted({m.group(1) for m in service.PLACEHOLDER.finditer(subject + body)})
            return Response({"detail": "Replace or remove these placeholders first: " + ", ".join(left)}, status=400)
        limit = int(getattr(settings, "OUTREACH_DAILY_LIMIT_PER_USER", 50))
        if service.sent_today_by(request.user) >= limit:
            return Response({"detail": f"You have reached today's limit of {limit} mails."}, status=429)
        warnings = service.warnings_for(rel, address)
        if warnings and request.data.get("confirm") is not True:
            return Response({"detail": "Please confirm.", "code": "needs_confirm", "warnings": warnings}, status=409)
        template = None
        if request.data.get("template_id"):
            template = EmailTemplate.objects.filter(pk=request.data.get("template_id")).first()
        log = service.deliver(rel, request.user, subject, body, template)
        if log.status == EmailLog.STATUS_FAILED:
            return Response({"detail": f"The mail could not be sent: {log.error or 'unknown error'}", "log": _log_row(log)}, status=502)
        return Response({"detail": "Mail sent." if log.status == EmailLog.STATUS_SENT else "Test mode: the mail was printed in the server window, not delivered.",
                         "log": _log_row(log)})


class LogView(APIView):
    """GET ?vessel=ID: the latest mail to each company about that vessel."""

    permission_classes = [IsAdminOrBDManager]

    def get(self, request):
        vessel = request.query_params.get("vessel", "")
        if not vessel.isdigit():
            return Response({"detail": "vessel is required."}, status=400)
        latest, counts = {}, {}
        for log in EmailLog.objects.filter(vessel_id=int(vessel)).exclude(status=EmailLog.STATUS_FAILED).select_related("sent_by"):
            counts[log.company_id] = counts.get(log.company_id, 0) + 1
            if log.company_id not in latest:        # newest first
                latest[log.company_id] = log
        rows = []
        for cid, log in latest.items():
            row = _log_row(log)
            row["count"] = counts[cid]
            rows.append(row)
        return Response({"results": rows})


# ---------- Pages "Email templates" and "Email log" (Admin and BD Manager) ----------

def _manage_row(t):
    row = _template_row(t)
    row.update({"active": t.active, "sort_order": t.sort_order, "updated_at": t.updated_at.isoformat()})
    return row


def _clean_template(data, instance=None):
    """Validate the fields of a template. Returns (values, errors)."""
    values, errors = {}, {}
    fields = ("name", "kind", "subject", "body", "active", "sort_order")
    for key in fields:
        if key in data:
            values[key] = data[key]
    if instance is None:
        for key in ("name", "subject", "body"):
            values.setdefault(key, "")
    for key in ("name", "subject"):
        if key in values:
            values[key] = service.clean_subject(values[key])
            if not values[key]:
                errors[key] = "This is required."
    if "name" in values and len(values["name"]) > 120:
        errors["name"] = "At most 120 characters."
    if "subject" in values and len(values["subject"]) > service.MAX_SUBJECT:
        errors["subject"] = f"At most {service.MAX_SUBJECT} characters."
    if "body" in values:
        values["body"] = str(values["body"] or "").replace("\r\n", "\n").strip()
        if not values["body"]:
            errors["body"] = "This is required."
        elif len(values["body"]) > service.MAX_BODY:
            errors["body"] = f"At most {service.MAX_BODY} characters."
    if "kind" in values and values["kind"] not in dict(EmailTemplate.KIND_CHOICES):
        errors["kind"] = "Choose first contact, reminder or other."
    if "active" in values:
        if not isinstance(values["active"], bool):
            errors["active"] = "Must be true or false."
    if "sort_order" in values:
        try:
            values["sort_order"] = max(0, min(int(values["sort_order"]), 100000))
        except (TypeError, ValueError):
            errors["sort_order"] = "Must be a whole number."
    return values, errors


class ManageTemplatesView(APIView):
    """GET: every template (also switched-off ones). POST: add one."""

    permission_classes = [IsAdminOrBDManager]

    def get(self, request):
        return Response({
            "mode": service.mode(), "enabled": service.enabled(),
            "placeholders": service.PLACEHOLDER_NAMES,
            "kinds": [{"value": v, "label": label} for v, label in EmailTemplate.KIND_CHOICES],
            "templates": [_manage_row(t) for t in EmailTemplate.objects.all()],
        })

    def post(self, request):
        values, errors = _clean_template(request.data)
        if errors:
            return Response({"detail": "Please fix the highlighted fields.", "errors": errors}, status=400)
        try:
            with transaction.atomic():
                t = EmailTemplate.objects.create(**values)
        except IntegrityError:
            return Response({"detail": "A template with this name already exists.", "errors": {"name": "Already used."}}, status=400)
        return Response(_manage_row(t), status=201)


class ManageTemplateDetailView(APIView):
    """PATCH: change a template (including switching it off)."""

    permission_classes = [IsAdminOrBDManager]

    def patch(self, request, pk):
        t = get_object_or_404(EmailTemplate, pk=pk)
        values, errors = _clean_template(request.data, instance=t)
        if errors:
            return Response({"detail": "Please fix the highlighted fields.", "errors": errors}, status=400)
        for key, value in values.items():
            setattr(t, key, value)
        try:
            with transaction.atomic():
                t.save()
        except IntegrityError:
            return Response({"detail": "A template with this name already exists.", "errors": {"name": "Already used."}}, status=400)
        return Response(_manage_row(t))


class HistoryView(APIView):
    """GET ?status=&q=&page=&page_size=: every mail sent from the app, newest first."""

    permission_classes = [IsAdminOrBDManager]

    def get(self, request):
        qs = EmailLog.objects.select_related("company", "vessel", "sent_by")
        status_filter = request.query_params.get("status", "")
        if status_filter in dict(EmailLog.STATUS_CHOICES):
            qs = qs.filter(status=status_filter)
        q = (request.query_params.get("q") or "").strip()[:100]
        if q:
            qs = qs.filter(Q(company__name__icontains=q) | Q(vessel__name__icontains=q)
                           | Q(to_email__icontains=q) | Q(subject__icontains=q))
        try:
            size = max(1, min(int(request.query_params.get("page_size", 25)), 100))
            page = max(1, int(request.query_params.get("page", 1)))
        except ValueError:
            return Response({"detail": "page and page_size must be numbers."}, status=400)
        count = qs.count()
        pages = max(1, -(-count // size))
        page = min(page, pages)
        rows = []
        for log in qs[(page - 1) * size: page * size]:
            row = _log_row(log)
            row.update({
                "to": log.to_email, "body": log.body, "error": log.error,
                "company": log.company.name if log.company else "",
                "vessel": log.vessel.name if log.vessel else "",
            })
            rows.append(row)
        return Response({"count": count, "page": page, "pages": pages, "results": rows})
