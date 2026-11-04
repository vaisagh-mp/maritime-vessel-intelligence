from django.conf import settings
from django.db import models

from apps.common.constants import (
    CLOSED_STAGES,
    ETA_SOURCE_CHOICES,
    OPPORTUNITY_STAGE_CHOICES,
    STAGE_DETECTED,
    ZONE_CHOICES,
)


class OpenOpportunityManager(models.Manager):
    def open_for(self, vessel, port):
        return self.filter(vessel=vessel, port=port).exclude(stage__in=CLOSED_STAGES)


class Opportunity(models.Model):
    vessel = models.ForeignKey(
        "vessels.Vessel", on_delete=models.CASCADE, related_name="opportunities"
    )
    port = models.ForeignKey(
        "ports.Port", on_delete=models.CASCADE, related_name="opportunities"
    )
    eta = models.DateTimeField(null=True, blank=True)
    eta_source = models.CharField(max_length=10, choices=ETA_SOURCE_CHOICES, blank=True)
    detected_at = models.DateTimeField(auto_now_add=True)
    zone = models.CharField(max_length=20, choices=ZONE_CHOICES)
    score = models.IntegerField(default=0)
    stage = models.CharField(
        max_length=30, choices=OPPORTUNITY_STAGE_CHOICES, default=STAGE_DETECTED
    )
    is_inbound = models.BooleanField(default=False)
    lead_reason = models.CharField(max_length=200, blank=True)

    updated_at = models.DateTimeField(auto_now=True)

    objects = OpenOpportunityManager()

    class Meta:
        db_table = "vi_opportunity"
        ordering = ["-detected_at"]

    def __str__(self):
        return f"{self.vessel} @ {self.port} [{self.stage}]"

    @property
    def is_open(self):
        return self.stage not in CLOSED_STAGES

    @property
    def band(self):
        """Priority band derived from score (HOT/HIGH/MEDIUM/LOW).
        Not persisted — always computed from the current score value."""
        from services.scoring_service import get_band
        return get_band(self.score)


class OpportunityNote(models.Model):
    opportunity = models.ForeignKey(
        "Opportunity", on_delete=models.CASCADE, related_name="notes"
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )
    text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "vi_opportunity_note"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Note on opp #{self.opportunity_id} by {self.author} @ {self.created_at}"

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise ValueError("OpportunityNote rows are append-only and cannot be updated.")
        super().save(*args, **kwargs)


class OpportunityStageChange(models.Model):
    opportunity = models.ForeignKey(
        "Opportunity", on_delete=models.CASCADE, related_name="stage_changes"
    )
    from_stage = models.CharField(max_length=30, blank=True)
    to_stage = models.CharField(max_length=30)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )
    changed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "vi_opportunity_stage_change"
        ordering = ["-changed_at"]

    def __str__(self):
        return f"Opp #{self.opportunity_id}: {self.from_stage} -> {self.to_stage} by {self.changed_by}"

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise ValueError("OpportunityStageChange rows are append-only and cannot be updated.")
        super().save(*args, **kwargs)

