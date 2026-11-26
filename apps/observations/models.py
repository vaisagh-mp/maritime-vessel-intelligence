from django.db import models

from apps.common.constants import PORT_AREA_CHOICES, PORT_AREA_UNKNOWN


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
    source = models.CharField(max_length=100)

    # Provider voyage, destination, and port area telemetry
    navigational_status = models.PositiveSmallIntegerField(null=True, blank=True)
    destination = models.CharField(max_length=120, blank=True)
    next_port_unlocode = models.CharField(max_length=10, blank=True)
    eta_calc = models.DateTimeField(null=True, blank=True)
    eta_updated = models.DateTimeField(null=True, blank=True)
    last_port = models.CharField(max_length=120, blank=True)
    last_port_unlocode = models.CharField(max_length=10, blank=True)
    last_port_time = models.DateTimeField(null=True, blank=True)
    current_port = models.CharField(max_length=120, blank=True)
    port_area = models.CharField(max_length=20, choices=PORT_AREA_CHOICES, default=PORT_AREA_UNKNOWN)

    class Meta:
        db_table = "vi_vessel_observation"
        ordering = ["-timestamp"]

    def __init__(self, *args, **kwargs):
        came_from = kwargs.pop("came_from_target_port", None)
        super().__init__(*args, **kwargs)
        if came_from is not None:
            self._came_from_target_port = bool(came_from)

    @property
    def came_from_target_port(self) -> bool:
        if hasattr(self, "_came_from_target_port"):
            return self._came_from_target_port
        target_unlocodes = {"AEFJR", "SGSIN"}
        if self.last_port_unlocode and self.last_port_unlocode.upper() in target_unlocodes:
            return True
        lp = (self.last_port or "").upper()
        if "FUJAIRAH" in lp or "SINGAPORE" in lp:
            return True
        return False

    @came_from_target_port.setter
    def came_from_target_port(self, value):
        self._came_from_target_port = bool(value)

    def __str__(self):
        return f"{self.vessel} @ {self.timestamp:%Y-%m-%d %H:%M}"

    def save(self, *args, **kwargs):
        # Defensive guard: observations are append-only, so refuse to update
        # an existing row — only inserts are allowed.
        if self.pk is not None:
            raise ValueError("VesselObservation rows are append-only and cannot be updated.")
        super().save(*args, **kwargs)
