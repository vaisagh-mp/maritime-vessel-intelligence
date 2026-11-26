from rest_framework import serializers

from .models import VesselObservation


class VesselObservationSerializer(serializers.ModelSerializer):
    class Meta:
        model = VesselObservation
        fields = [
            "id",
            "vessel",
            "timestamp",
            "latitude",
            "longitude",
            "speed",
            "course",
            "source",
            "navigational_status",
            "destination",
            "next_port_unlocode",
            "eta_calc",
            "eta_updated",
            "last_port",
            "last_port_unlocode",
            "last_port_time",
            "current_port",
            "port_area",
        ]
        read_only_fields = fields
