from django.contrib import admin

from .models import Vessel


class HasCompanyRelationshipFilter(admin.SimpleListFilter):
    title = "enriched (has company relationship)"
    parameter_name = "enriched"

    def lookups(self, request, model_admin):
        return [("yes", "Yes"), ("no", "No")]

    def queryset(self, request, queryset):
        if self.value() == "yes":
            return queryset.filter(relationships__isnull=False).distinct()
        if self.value() == "no":
            return queryset.filter(relationships__isnull=True)
        return queryset


@admin.register(Vessel)
class VesselAdmin(admin.ModelAdmin):
    list_display = ["name", "mmsi", "imo", "vessel_type", "dwt", "updated_at"]
    list_filter = [HasCompanyRelationshipFilter, "vessel_type"]
    search_fields = ["name", "mmsi", "imo"]
    ordering = ["name"]
