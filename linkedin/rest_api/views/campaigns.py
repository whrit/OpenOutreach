from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import status

from linkedin.models import Campaign
from linkedin.rest_api.authentication import ApiKeyAuthentication
from linkedin.rest_api.permissions import HasApiKey
from linkedin.rest_api.serializers import CampaignSerializer

# Fields that API consumers are allowed to modify via PATCH.
_PATCHABLE_FIELDS = {"product_docs", "campaign_objective", "followup_template", "booking_link"}


class CampaignListView(APIView):
    """
    GET /campaigns/ — return all campaigns.
    """

    authentication_classes = [ApiKeyAuthentication]
    permission_classes = [HasApiKey]

    def get(self, request):
        campaigns = Campaign.objects.select_related("department").all()
        serializer = CampaignSerializer(campaigns, many=True)
        return Response(serializer.data)


class CampaignDetailView(APIView):
    """
    GET  /campaigns/{id}/ — retrieve a single campaign.
    PATCH /campaigns/{id}/ — partially update writable fields only.

    Read-only fields (id, department_name, is_partner, action_fraction) are
    enforced by CampaignSerializer.Meta.read_only_fields, so any attempt to
    change them via PATCH is silently ignored by the serializer.
    """

    authentication_classes = [ApiKeyAuthentication]
    permission_classes = [HasApiKey]

    def _get_campaign(self, pk: int):
        """Return Campaign or None."""
        try:
            return Campaign.objects.select_related("department").get(pk=pk)
        except Campaign.DoesNotExist:
            return None

    def get(self, request, pk: int):
        campaign = self._get_campaign(pk)
        if campaign is None:
            return Response({"error": "Campaign not found"}, status=status.HTTP_404_NOT_FOUND)
        serializer = CampaignSerializer(campaign)
        return Response(serializer.data)

    def patch(self, request, pk: int):
        campaign = self._get_campaign(pk)
        if campaign is None:
            return Response({"error": "Campaign not found"}, status=status.HTTP_404_NOT_FOUND)

        # Strip any keys that are not in the patchable allow-list so that
        # read-only fields cannot be modified even if the serializer were to
        # relax its read_only_fields in the future.
        allowed_data = {k: v for k, v in request.data.items() if k in _PATCHABLE_FIELDS}

        serializer = CampaignSerializer(campaign, data=allowed_data, partial=True)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        serializer.save()
        return Response(serializer.data)
