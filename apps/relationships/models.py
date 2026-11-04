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
        max_length=100, help_text="Provenance of this relationship, e.g. kpler:vessels."
    )
    verified = models.BooleanField(
        default=False,
        help_text=(
            "Registry-derived relationships are unverified public data, "
            "not a human-confirmed named decision-maker."
        ),
    )
    last_verified_date = models.DateField(null=True, blank=True)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    is_current = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "vi_vessel_relationship"
        ordering = ["-created_at"]
        # TODO(step 8): historical entries may need unique_vessel_company_role relaxed
        constraints = [
            models.UniqueConstraint(
                fields=["vessel", "company", "role"],
                name="unique_vessel_company_role",
            )
        ]

    def __str__(self):
        return f"{self.vessel} — {self.company} ({self.role})"
