from django.contrib import admin

from .models import VesselObservation


@admin.register(VesselObservation)
class VesselObservationAdmin(admin.ModelAdmin):
    list_display = ["vessel", "timestamp", "latitude", "longitude", "speed", "course", "port_area", "source"]
    list_filter = ["source", "port_area"]
    search_fields = ["vessel__name", "vessel__mmsi"]
    date_hierarchy = "timestamp"

    def has_change_permission(self, request, obj=None):
        # Append-only: admin can view but never edit an observation.
        return False
