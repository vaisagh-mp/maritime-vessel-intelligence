from django.db import models


class EnrichmentLog(models.Model):
    """Auditable record of every paid DataDocked call — logged on both success
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
