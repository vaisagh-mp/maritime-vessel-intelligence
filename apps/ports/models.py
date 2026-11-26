from django.db import models


class Port(models.Model):
    name = models.CharField(max_length=200)
    un_locode = models.CharField(
        "UN/LOCODE", max_length=10, unique=True, help_text="e.g. AEFJR for Fujairah"
    )
    latitude = models.FloatField()
    longitude = models.FloatField()
    anchorage_latitude = models.FloatField(
        help_text="Center point used for the discovery geofence scan."
    )
    anchorage_longitude = models.FloatField(
        help_text="Center point used for the discovery geofence scan."
    )
    geofence_radius_km = models.FloatField(
        help_text="Radius (km) around the anchorage centre point used for the area scan."
    )
    marinetraffic_port_id = models.PositiveIntegerField(
        null=True, blank=True, unique=True, help_text="MarineTraffic port identifier."
    )
    ais_filter = models.TextField(
        blank=True,
        help_text="Provider area filter for the AIS call. Empty until the provider confirms the area.",
    )
    active = models.BooleanField(
        default=True, help_text="Only active ports are polled by the discovery task."
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "vi_port"
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.un_locode})"
