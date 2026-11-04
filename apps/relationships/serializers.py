from rest_framework import serializers

from .models import VesselRelationship


class VesselRelationshipSerializer(serializers.ModelSerializer):
    role_label = serializers.CharField(source="get_role_display", read_only=True)
    company_detail = serializers.SerializerMethodField()

    class Meta:
        model = VesselRelationship
        fields = [
            "id",
            "vessel",
            "company",
            "company_detail",
            "role",
            "role_label",
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

    def get_company_detail(self, obj):
        c = obj.company
        if not c:
            return None
        return {
            "id": c.id,
            "name": c.name,
            "company_type": c.company_type,
            "country": c.country,
            "email": c.email,
            "website": c.website,
            "address": c.address,
        }

