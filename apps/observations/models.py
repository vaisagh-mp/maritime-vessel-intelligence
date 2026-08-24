from django.db import models


class VesselObservation(models.Model):
    """Append-only log of raw position pings. Never updated or overwritten —
    every discovery poll creates a new row, even for a vessel seen before."""

    vessel = models.ForeignKey(
        "vessels.Vessel", on_delete=models.CASCADE, related_name="observations"
    )
    timestamp = models.DateTimeField(db_index=True)
    latitude = models.FloatField()
    longitude = models.FloatField()
    speed = models.FloatField(null=True, blank=True)
    course = models.FloatField(null=True, blank=True)
    source = models.CharField(max_length=100, default="datadocked.com")

    class Meta:
        db_table = "vi_vessel_observation"
        ordering = ["-timestamp"]

    def __str__(self):
        return f"{self.vessel} @ {self.timestamp:%Y-%m-%d %H:%M}"

    def save(self, *args, **kwargs):
        # Defensive guard: observations are append-only, so refuse to update
        # an existing row — only inserts are allowed.
        if self.pk is not None:
            raise ValueError("VesselObservation rows are append-only and cannot be updated.")
        super().save(*args, **kwargs)
