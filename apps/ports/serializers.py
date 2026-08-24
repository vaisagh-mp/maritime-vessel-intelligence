from rest_framework import serializers

from .models import Port


class PortSerializer(serializers.ModelSerializer):
    class Meta:
        model = Port
        fields = [
            "id",
            "name",
            "un_locode",
            "latitude",
            "longitude",
            "anchorage_latitude",
            "anchorage_longitude",
            "geofence_radius_km",
            "active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]
