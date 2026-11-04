from rest_framework import serializers

from apps.common.constants import OPPORTUNITY_STAGE_CHOICES

from .models import Opportunity


class OpportunitySerializer(serializers.ModelSerializer):
    band = serializers.SerializerMethodField()

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
            "score",
            "band",
            "stage",
            "is_inbound",
            "lead_reason",
            "updated_at",
        ]
        read_only_fields = [f for f in fields if f != "stage"]

    def get_band(self, obj):
        return obj.band


class OpportunityStageUpdateSerializer(serializers.ModelSerializer):
    """Used only for the PATCH endpoint — the sole manually-editable field."""

    stage = serializers.ChoiceField(choices=OPPORTUNITY_STAGE_CHOICES)

    class Meta:
        model = Opportunity
        fields = ["stage"]
