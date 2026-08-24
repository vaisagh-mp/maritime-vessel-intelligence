from django.contrib import admin

from .models import Port


@admin.register(Port)
class PortAdmin(admin.ModelAdmin):
    list_display = ["name", "un_locode", "geofence_radius_km", "active", "updated_at"]
    list_filter = ["active"]
    search_fields = ["name", "un_locode"]
    ordering = ["name"]
