from rest_framework import serializers

from linkedin.models import ActionJob, Campaign, WebhookSubscription


class ProfileStateSerializer(serializers.Serializer):
    """Read-only profile summary returned from CRM queries."""
    public_id = serializers.CharField()
    url = serializers.CharField()
    state = serializers.CharField()
    first_name = serializers.CharField(allow_blank=True)
    last_name = serializers.CharField(allow_blank=True)
    title = serializers.CharField(allow_blank=True)
    company = serializers.CharField(allow_blank=True)


class ProfileInjectSerializer(serializers.Serializer):
    """Inject one or more LinkedIn profile URLs into the pipeline."""
    urls = serializers.ListField(
        child=serializers.URLField(),
        min_length=1,
        max_length=100,
    )
    campaign_id = serializers.IntegerField()


class CampaignSerializer(serializers.ModelSerializer):
    department_name = serializers.CharField(source="department.name", read_only=True)

    class Meta:
        model = Campaign
        fields = [
            "id", "department_name", "product_docs", "campaign_objective",
            "followup_template", "booking_link", "is_partner", "action_fraction",
        ]
        read_only_fields = ["id", "department_name", "is_partner", "action_fraction"]


class ActionJobSerializer(serializers.ModelSerializer):
    class Meta:
        model = ActionJob
        fields = ["id", "lane", "params", "status", "result", "campaign_id", "created_at", "updated_at"]
        read_only_fields = ["id", "status", "result", "created_at", "updated_at"]


class LaneTriggerSerializer(serializers.Serializer):
    LANE_CHOICES = [c[0] for c in ActionJob.LANE_CHOICES]
    lane = serializers.ChoiceField(choices=LANE_CHOICES)
    campaign_id = serializers.IntegerField()
    params = serializers.DictField(default=dict)


class WebhookSerializer(serializers.ModelSerializer):
    # Explicitly declare campaign_id as a writable integer field.
    # Without this, DRF ModelSerializer generates campaign_id as ReadOnlyField
    # (the _id suffix of a FK is not writable by default), which means it would
    # never appear in validated_data and campaign filtering would be silently skipped.
    campaign_id = serializers.IntegerField(required=False, allow_null=True)

    class Meta:
        model = WebhookSubscription
        fields = ["id", "url", "events", "campaign_id", "active", "created_at"]
        read_only_fields = ["id", "created_at"]
