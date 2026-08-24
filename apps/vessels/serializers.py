from rest_framework import serializers

from .models import Vessel


class VesselSerializer(serializers.ModelSerializer):
    class Meta:
        model = Vessel
        fields = [
            "id",
            "imo",
            "mmsi",
            "name",
            "vessel_type",
            "dwt",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields
