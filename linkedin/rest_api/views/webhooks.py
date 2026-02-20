"""Webhook registration views: list/create and delete."""
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from linkedin.models import Campaign, WebhookSubscription
from linkedin.rest_api.authentication import ApiKeyAuthentication
from linkedin.rest_api.permissions import HasApiKey
from linkedin.rest_api.serializers import WebhookSerializer

VALID_EVENTS = frozenset(["job.completed", "job.failed"])
# Note: "profile.state_changed" removed — not yet implemented. Add back when
# dispatch_webhooks is called from crm_profiles.py state transitions.


class WebhookListCreateView(APIView):
    """
    GET  /webhooks/ — list all WebhookSubscription objects.
    POST /webhooks/ — register a new subscription.
    """

    authentication_classes = [ApiKeyAuthentication]
    permission_classes = [HasApiKey]

    def get(self, request):
        subscriptions = WebhookSubscription.objects.all()
        serializer = WebhookSerializer(subscriptions, many=True)
        return Response(serializer.data)

    def post(self, request):
        # --- Validate url via serializer (it uses URLField) ---
        serializer = WebhookSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        # --- Validate events ---
        events = serializer.validated_data.get("events", [])
        if not events:
            return Response(
                {"events": "This field is required and must be a non-empty list."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        invalid = [e for e in events if e not in VALID_EVENTS]
        if invalid:
            return Response(
                {"events": f"Invalid event(s): {invalid}. Valid choices are: {sorted(VALID_EVENTS)}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # --- Resolve campaign FK (optional) ---
        # Read from validated_data to guarantee an integer (or None); reading
        # from request.data directly could yield a string or other non-integer
        # type, causing the ORM to raise ValueError instead of DoesNotExist.
        campaign_id = serializer.validated_data.get("campaign_id")
        campaign = None
        if campaign_id is not None:
            try:
                campaign = Campaign.objects.get(pk=campaign_id)
            except Campaign.DoesNotExist:
                return Response(
                    {"error": f"Campaign {campaign_id} not found."},
                    status=status.HTTP_404_NOT_FOUND,
                )

        subscription = WebhookSubscription.objects.create(
            url=serializer.validated_data["url"],
            events=events,
            campaign=campaign,
            active=serializer.validated_data.get("active", True),
        )
        out = WebhookSerializer(subscription)
        return Response(out.data, status=status.HTTP_201_CREATED)


class WebhookDetailView(APIView):
    """
    DELETE /webhooks/{id}/ — delete a subscription (204). Returns 404 if not found.
    """

    authentication_classes = [ApiKeyAuthentication]
    permission_classes = [HasApiKey]

    def delete(self, request, pk: int):
        try:
            subscription = WebhookSubscription.objects.get(pk=pk)
        except WebhookSubscription.DoesNotExist:
            return Response(
                {"error": "WebhookSubscription not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        subscription.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
