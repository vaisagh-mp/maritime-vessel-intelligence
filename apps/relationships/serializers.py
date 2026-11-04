from rest_framework import serializers

from .models import VesselRelationship


class VesselRelationshipSerializer(serializers.ModelSerializer):
    class Meta:
        model = VesselRelationship
        fields = [
            "id",
            "vessel",
            "company",
            "role",
            "source",
            "verified",
            "last_verified_date",
            "start_date",
            "end_date",
            "is_current",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields
