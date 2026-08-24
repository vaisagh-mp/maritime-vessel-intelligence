from rest_framework import serializers

from .models import VesselObservation


class VesselObservationSerializer(serializers.ModelSerializer):
    class Meta:
        model = VesselObservation
        fields = ["id", "vessel", "timestamp", "latitude", "longitude", "speed", "course", "source"]
        read_only_fields = fields
