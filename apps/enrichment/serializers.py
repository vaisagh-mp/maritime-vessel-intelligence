from rest_framework import serializers

from .models import EnrichmentLog


class EnrichmentLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = EnrichmentLog
        fields = ["id", "vessel", "port", "endpoint_called", "timestamp", "success", "credits_spent", "error_message"]
        read_only_fields = fields
