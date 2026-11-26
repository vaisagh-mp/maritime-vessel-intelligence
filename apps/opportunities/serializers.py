from rest_framework import serializers

from apps.common.constants import OPPORTUNITY_STAGE_CHOICES, ZONE_CHOICES
from .models import Opportunity, OpportunityNote, OpportunityStageChange


class UserSummarySerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    username = serializers.CharField(read_only=True)
    full_name = serializers.SerializerMethodField()

    def get_full_name(self, obj):
        return obj.get_full_name() if obj else ""


class OpportunityNoteSerializer(serializers.ModelSerializer):
    author = UserSummarySerializer(read_only=True)

    class Meta:
        model = OpportunityNote
        fields = ["id", "text", "author", "created_at"]
        read_only_fields = fields


class OpportunityStageChangeSerializer(serializers.ModelSerializer):
    from_stage_label = serializers.SerializerMethodField()
    to_stage_label = serializers.SerializerMethodField()
    changed_by = UserSummarySerializer(read_only=True)

    class Meta:
        model = OpportunityStageChange
        fields = [
            "id",
            "from_stage",
            "from_stage_label",
            "to_stage",
            "to_stage_label",
            "changed_by",
            "changed_at",
        ]
        read_only_fields = fields

    def get_from_stage_label(self, obj):
        return dict(OPPORTUNITY_STAGE_CHOICES).get(obj.from_stage, obj.from_stage)

    def get_to_stage_label(self, obj):
        return dict(OPPORTUNITY_STAGE_CHOICES).get(obj.to_stage, obj.to_stage)


class OpportunitySerializer(serializers.ModelSerializer):
    band = serializers.SerializerMethodField()
    vessel_summary = serializers.SerializerMethodField()
    port_summary = serializers.SerializerMethodField()
    stage_label = serializers.CharField(source="get_stage_display", read_only=True)
    zone_label = serializers.CharField(source="get_zone_display", read_only=True)

    class Meta:
        model = Opportunity
        fields = [
            "id",
            "vessel",
            "port",
            "eta",
            "eta_source",
            "detected_at",
            "zone",
            "zone_label",
            "score",
            "band",
            "stage",
            "stage_label",
            "is_inbound",
            "lead_reason",
            "vessel_summary",
            "port_summary",
            "updated_at",
        ]
        read_only_fields = [f for f in fields if f != "stage"]

    def get_band(self, obj):
        return obj.band

    def get_vessel_summary(self, obj):
        v = obj.vessel
        if not v:
            return None
        return {
            "id": v.id,
            "name": v.name,
            "imo": v.imo,
            "mmsi": v.mmsi,
            "vessel_type": v.vessel_type,
            "grt": v.grt,
            "dwt": v.dwt,
            "flag": v.flag,
            "year_built": v.year_built,
        }

    def get_port_summary(self, obj):
        p = obj.port
        if not p:
            return None
        return {
            "id": p.id,
            "name": p.name,
            "un_locode": p.un_locode,
        }


class OpportunityStageUpdateSerializer(serializers.ModelSerializer):
    """Used only for the PATCH endpoint — the sole manually-editable field."""

    stage = serializers.ChoiceField(choices=OPPORTUNITY_STAGE_CHOICES)

    class Meta:
        model = Opportunity
        fields = ["stage"]

