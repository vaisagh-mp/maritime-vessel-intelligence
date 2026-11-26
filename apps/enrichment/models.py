from django.conf import settings
from django.db import models


class EnrichmentLog(models.Model):
    """Auditable record of every data provider call — logged on both success
    and failure so credit spend stays traceable.

    ``vessel`` is nullable to support port-level calls (e.g. expected-arrivals)
    where no single vessel identifier is used. At least one of ``vessel`` or
    ``port`` will always be set by the logging helpers.
    """

    vessel = models.ForeignKey(
        "vessels.Vessel",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="enrichment_logs",
    )
    port = models.ForeignKey(
        "ports.Port",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="enrichment_logs",
    )
    endpoint_called = models.CharField(max_length=100)
    timestamp = models.DateTimeField(auto_now_add=True)
    success = models.BooleanField()
    credits_spent = models.IntegerField(default=0)
    error_message = models.TextField(blank=True)

    class Meta:
        db_table = "vi_enrichment_log"
        ordering = ["-timestamp"]

    def __str__(self):
        subject = str(self.vessel) if self.vessel_id else f"port:{self.port}"
        status = "OK" if self.success else "FAILED"
        return f"{subject} — {self.endpoint_called} [{status}]"


class ProviderCallState(models.Model):
    """One row per data provider holding the time of its last live call.

    Used by the "Refresh data (live)" button to enforce the provider's rate
    limit on the SERVER (shared by every user and every port).
    """

    provider = models.CharField(max_length=40, unique=True)
    last_call_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "vi_provider_call_state"

    def __str__(self):
        return f"{self.provider} (last call {self.last_call_at})"


class IngestRun(models.Model):
    """Record of one live refresh started from the web app."""

    STATUS_RUNNING = "running"
    STATUS_SUCCESS = "success"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [
        (STATUS_RUNNING, "Running"),
        (STATUS_SUCCESS, "Success"),
        (STATUS_FAILED, "Failed"),
    ]

    port_code = models.CharField(max_length=10)
    mode = models.CharField(max_length=20, default="arrivals")
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=STATUS_RUNNING)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="ingest_runs",
    )
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    summary = models.JSONField(default=dict, blank=True)
    error = models.CharField(max_length=300, blank=True)

    class Meta:
        db_table = "vi_ingest_run"
        ordering = ["-started_at", "-id"]

    def __str__(self):
        return f"{self.port_code} {self.mode} [{self.status}]"


class ArrivalsFetch(models.Model):
    """One live Expected Arrivals fetch of one port, and the vessels it saved."""

    port = models.ForeignKey("ports.Port", on_delete=models.CASCADE, related_name="arrivals_fetches")
    fetched_at = models.DateTimeField(db_index=True)
    vessel_count = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "vi_arrivals_fetch"
        ordering = ["-fetched_at"]

    def __str__(self):
        return f"{self.port_id} {self.fetched_at:%Y-%m-%d %H:%M} ({self.vessel_count})"


class ArrivalsFetchItem(models.Model):
    """A vessel saved by an arrivals fetch, with the lead values at that moment."""

    fetch = models.ForeignKey(ArrivalsFetch, on_delete=models.CASCADE, related_name="items")
    vessel = models.ForeignKey("vessels.Vessel", on_delete=models.CASCADE, related_name="arrivals_fetch_items")
    opportunity = models.ForeignKey(
        "opportunities.Opportunity", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    eta = models.DateTimeField(null=True, blank=True)
    zone = models.CharField(max_length=20, blank=True)
    score = models.IntegerField(default=0)

    class Meta:
        db_table = "vi_arrivals_fetch_item"
        constraints = [models.UniqueConstraint(fields=["fetch", "vessel"], name="uniq_arrivals_fetch_vessel")]


def record_arrivals_fetch(port, pairs, when=None):
    """Save the (vessel, opportunity) pairs of one port fetch. Safe to call inside a transaction."""
    from django.utils import timezone

    seen, items = set(), []
    fetch = ArrivalsFetch.objects.create(port=port, fetched_at=when or timezone.now())
    for vessel, opp in pairs:
        if vessel.pk in seen:
            continue
        seen.add(vessel.pk)
        items.append(ArrivalsFetchItem(
            fetch=fetch, vessel=vessel, opportunity=opp, eta=opp.eta, zone=opp.zone, score=opp.score,
        ))
    ArrivalsFetchItem.objects.bulk_create(items)
    fetch.vessel_count = len(items)
    fetch.save(update_fields=["vessel_count"])
    return fetch
