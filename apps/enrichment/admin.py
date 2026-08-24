from django.contrib import admin

from .models import EnrichmentLog


@admin.register(EnrichmentLog)
class EnrichmentLogAdmin(admin.ModelAdmin):
    list_display = ["subject_display", "endpoint_called", "success", "credits_spent", "timestamp"]
    list_filter = ["endpoint_called", "success", "port"]
    search_fields = ["vessel__name", "vessel__mmsi", "port__name", "port__un_locode"]
    date_hierarchy = "timestamp"

    @admin.display(description="Vessel / Port")
    def subject_display(self, obj):
        """Show vessel name+MMSI for vessel-level rows, port name for port-level rows."""
        if obj.vessel_id:
            return str(obj.vessel)
        if obj.port_id:
            return f"[port] {obj.port}"
        return "—"

    def has_change_permission(self, request, obj=None):
        return False
