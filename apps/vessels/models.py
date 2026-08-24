from django.db import models


class Vessel(models.Model):
    # DataDocked's area-scan endpoint does not return IMO, so MMSI is the
    # discovery dedup key; IMO is filled in later by enrichment when available.
    imo = models.CharField(max_length=20, null=True, blank=True, db_index=True)
    mmsi = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=200)
    vessel_type = models.CharField(max_length=120, blank=True)
    dwt = models.FloatField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "vi_vessel"
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} (MMSI {self.mmsi})"

    @property
    def is_enriched(self):
        """True once the vessel has at least one company relationship
        resolved by enrichment — used as an admin filter."""
        return self.relationships.exists()
