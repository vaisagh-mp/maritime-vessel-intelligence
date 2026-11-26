from django.conf import settings
from django.db import models
from django.utils import timezone


class EmailTemplate(models.Model):
    """A reusable email. Edited in the Django admin; used by the "Send mail" button."""

    KIND_FIRST = "first_contact"
    KIND_REMINDER = "reminder"
    KIND_OTHER = "other"
    KIND_CHOICES = [
        (KIND_FIRST, "First contact (72 hours before arrival)"),
        (KIND_REMINDER, "Reminder (24 hours before arrival)"),
        (KIND_OTHER, "Other"),
    ]

    name = models.CharField(max_length=120, unique=True)
    kind = models.CharField(max_length=20, choices=KIND_CHOICES, default=KIND_OTHER)
    subject = models.CharField(max_length=200)
    body = models.TextField(
        help_text="Plain text. Placeholders: {{company_name}}, {{vessel_name}}, {{imo}}, {{vessel_type}}, "
                  "{{grt}}, {{flag}}, {{port}}, {{eta}}, {{role}}, {{sender_name}}, {{sender_first_name}}."
    )
    active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=100)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "vi_email_template"
        ordering = ["sort_order", "name"]

    def __str__(self):
        return self.name


class EmailLog(models.Model):
    """Every mail sent (or tried) from the app. Never edited."""

    STATUS_SENT = "sent"
    STATUS_TEST = "test"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [(STATUS_SENT, "Sent"), (STATUS_TEST, "Test (not delivered)"), (STATUS_FAILED, "Failed")]

    company = models.ForeignKey("companies.Company", null=True, on_delete=models.SET_NULL, related_name="email_logs")
    vessel = models.ForeignKey("vessels.Vessel", null=True, blank=True, on_delete=models.SET_NULL, related_name="email_logs")
    opportunity = models.ForeignKey("opportunities.Opportunity", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    relationship = models.ForeignKey("relationships.VesselRelationship", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    template = models.ForeignKey(EmailTemplate, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    template_name = models.CharField(max_length=120, blank=True)
    to_email = models.EmailField()
    subject = models.CharField(max_length=200)
    body = models.TextField()
    sent_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    sent_at = models.DateTimeField(default=timezone.now, db_index=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES)
    error = models.CharField(max_length=300, blank=True)

    class Meta:
        db_table = "vi_email_log"
        ordering = ["-sent_at"]
        indexes = [models.Index(fields=["company", "vessel", "-sent_at"], name="vi_emaillog_co_ve_sent")]

    def __str__(self):
        return f"{self.sent_at:%Y-%m-%d %H:%M} to {self.to_email} ({self.status})"
