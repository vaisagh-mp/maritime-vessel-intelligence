from django.db import models

from apps.common.constants import COMPANY_TYPE_CHOICES, PRIORITY_CHOICES


class Company(models.Model):
    name = models.CharField(max_length=255, db_index=True)
    company_type = models.CharField(max_length=20, choices=COMPANY_TYPE_CHOICES)
    priority = models.CharField(
        max_length=10, choices=PRIORITY_CHOICES, default="medium"
    )
    email = models.EmailField(blank=True)
    website = models.URLField(blank=True)
    address = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "vi_company"
        ordering = ["name"]
        verbose_name_plural = "companies"

    def __str__(self):
        return self.name
