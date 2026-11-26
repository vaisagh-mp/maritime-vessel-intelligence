from django.contrib import admin

from .models import Port


@admin.register(Port)
class PortAdmin(admin.ModelAdmin):
    list_display = ["name", "un_locode", "geofence_radius_km", "has_ais_filter", "active", "updated_at"]
    list_filter = ["active"]
    search_fields = ["name", "un_locode"]
    ordering = ["name"]

    @admin.display(boolean=True, description="AIS area filter")
    def has_ais_filter(self, obj):
        return bool((obj.ais_filter or "").strip())
