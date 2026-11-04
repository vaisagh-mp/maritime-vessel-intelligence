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
            "grt",
            "flag",
            "year_built",
            "length",
            "beam",
            "draught",
            "callsign",
            "ship_id",
            "vessel_type_code",
            "vessel_size_segment",
            "last_dry_dock",
            "last_renewal_survey",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields
