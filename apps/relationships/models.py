from django.db import models

from apps.common.constants import RELATIONSHIP_ROLE_CHOICES


class VesselRelationship(models.Model):
    vessel = models.ForeignKey(
        "vessels.Vessel", on_delete=models.CASCADE, related_name="relationships"
    )
    company = models.ForeignKey(
        "companies.Company", on_delete=models.CASCADE, related_name="vessel_relationships"
    )
    role = models.CharField(max_length=20, choices=RELATIONSHIP_ROLE_CHOICES)
    source = models.CharField(
        max_length=100, help_text="e.g. datadocked.com — provenance of this relationship."
    )
    verified = models.BooleanField(
        default=False,
        help_text=(
            "Registry-derived relationships (e.g. from DataDocked management data) "
            "are unverified public data, not a human-confirmed named decision-maker."
        ),
    )
    last_verified_date = models.DateField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "vi_vessel_relationship"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["vessel", "company", "role"],
                name="unique_vessel_company_role",
            )
        ]

    def __str__(self):
        return f"{self.vessel} — {self.company} ({self.role})"
