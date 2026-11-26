from django.contrib import admin

from .models import Company


@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ["name", "company_type", "priority", "vessel_count", "email", "updated_at"]
    list_filter = ["company_type", "priority"]
    search_fields = ["name", "email"]
    ordering = ["name"]

    @admin.display(description="Vessels", ordering="name")
    def vessel_count(self, obj):
        """Distinct vessel count — computed per-row, acceptable at Phase 1 scale."""
        return obj.vessel_relationships.values("vessel").distinct().count()
