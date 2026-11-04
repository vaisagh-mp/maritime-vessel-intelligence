from django.db import models

from apps.common.utils import normalize_imo


class Vessel(models.Model):
    # Vessel identification: MMSI is the primary discovery key; IMO is filled in
    # later by enrichment when available.
    imo = models.CharField(max_length=20, null=True, blank=True, db_index=True)
    mmsi = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=200)
    vessel_type = models.CharField(max_length=120, blank=True)
    dwt = models.FloatField(null=True, blank=True)

    # Particulars and registry data from provider
    grt = models.FloatField(null=True, blank=True, help_text="Gross tonnage")
    flag = models.CharField(max_length=60, blank=True)
    year_built = models.PositiveSmallIntegerField(null=True, blank=True)
    length = models.FloatField(null=True, blank=True, help_text="Length in metres")
    beam = models.FloatField(null=True, blank=True, help_text="Beam in metres")
    draught = models.FloatField(null=True, blank=True, help_text="Draught in metres")
    callsign = models.CharField(max_length=20, blank=True)
    ship_id = models.CharField(max_length=20, blank=True)
    vessel_type_code = models.CharField(max_length=10, blank=True)
    vessel_size_segment = models.CharField(max_length=60, blank=True)
    last_dry_dock = models.DateField(null=True, blank=True)
    last_renewal_survey = models.DateField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "vi_vessel"
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} (MMSI {self.mmsi})"

    def save(self, *args, **kwargs):
        # Providers send "", "0" etc. for a missing IMO; never store a placeholder.
        # (Callers using update_fields must include "imo" for this to persist.)
        self.imo = normalize_imo(self.imo)
        super().save(*args, **kwargs)

    @property
    def is_enriched(self):
        """True once the vessel has at least one company relationship
        resolved by enrichment — used as an admin filter."""
        return self.relationships.exists()
