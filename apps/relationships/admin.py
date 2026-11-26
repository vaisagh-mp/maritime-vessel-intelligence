from django.contrib import admin

from .models import VesselRelationship


@admin.register(VesselRelationship)
class VesselRelationshipAdmin(admin.ModelAdmin):
    list_display = ["vessel", "company", "role", "source", "verified", "last_verified_date", "verified_by"]
    list_filter = ["role", "verified", "source"]
    search_fields = ["vessel__name", "vessel__mmsi", "company__name"]
    autocomplete_fields = ["vessel", "company"]
