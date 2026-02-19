import json

from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import status

from linkedin.db.crm_profiles import (
    lead_exists,
    public_id_to_url,
    url_to_public_id,
)
from linkedin.rest_api.authentication import ApiKeyAuthentication
from linkedin.rest_api.permissions import HasApiKey
from linkedin.rest_api.serializers import ProfileInjectSerializer


def _lead_to_dict(lead) -> dict:
    """Convert a Lead ORM object to a profile summary dict."""
    from crm.models import Deal

    public_id = url_to_public_id(lead.website) if lead.website else ""

    deal = Deal.objects.filter(lead=lead).first()
    if deal and deal.stage:
        state = deal.stage.name.lower()
    elif getattr(lead, "disqualified", False):
        state = "disqualified"
    elif lead.description:
        state = "enriched"
    else:
        state = "url_only"

    positions = []
    if lead.description:
        try:
            profile = json.loads(lead.description)
            positions = profile.get("positions", [])
        except (json.JSONDecodeError, TypeError):
            pass

    return {
        "public_id": public_id,
        "url": lead.website or "",
        "state": state,
        "first_name": lead.first_name or "",
        "last_name": lead.last_name or "",
        "title": lead.title or "",
        "company": positions[0].get("company_name", "") if positions else "",
    }


class ProfileListView(APIView):
    authentication_classes = [ApiKeyAuthentication]
    permission_classes = [HasApiKey]

    def get(self, request):
        """List profiles, optionally filtered by state."""
        from crm.models import Lead, Deal

        state_filter = request.query_params.get("state")
        qs = Lead.objects.all()

        if state_filter == "disqualified":
            qs = qs.filter(disqualified=True)
        elif state_filter == "enriched":
            qs = qs.filter(
                disqualified=False, contact__isnull=True
            ).exclude(description="").exclude(description__isnull=True)
        elif state_filter == "url_only":
            # description is null=False, blank=True — url_only leads have empty string
            qs = qs.filter(disqualified=False, contact__isnull=True).filter(
                description=""
            )
        elif state_filter in ("new", "pending", "connected", "completed", "failed"):
            stage_name = state_filter.capitalize()
            deal_lead_ids = Deal.objects.filter(
                stage__name=stage_name
            ).values_list("lead_id", flat=True)
            qs = qs.filter(pk__in=deal_lead_ids)

        campaign_id = request.query_params.get("campaign_id")
        if campaign_id:
            qs = qs.filter(department__campaign__id=campaign_id)

        data = [_lead_to_dict(lead) for lead in qs[:200]]
        return Response(data)

    def post(self, request):
        """Inject profile URLs into the pipeline."""
        from crm.models import Lead

        ser = ProfileInjectSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        from linkedin.models import Campaign

        try:
            campaign = Campaign.objects.select_related("department").get(
                pk=ser.validated_data["campaign_id"]
            )
        except Campaign.DoesNotExist:
            return Response({"error": "Campaign not found"}, status=status.HTTP_404_NOT_FOUND)

        # Resolve the department owner for Lead creation.
        # Department is a Group subclass — use user_set to find members.
        from django.contrib.auth.models import User
        dept_user = campaign.department.user_set.filter(is_active=True).first()
        if dept_user is None:
            dept_user = User.objects.filter(is_staff=True, is_active=True).first()
        if dept_user is None:
            return Response(
                {"error": "No owner user found for campaign department"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        # Build a minimal session-like object for _get_lead_source
        class _MinimalSession:
            django_user = dept_user

            def __init__(self, c):
                self.campaign = c

        session = _MinimalSession(campaign)

        results = []
        for url in ser.validated_data["urls"]:
            public_id = url_to_public_id(url)
            if not public_id:
                results.append({"url": url, "status": "invalid_url"})
                continue
            if lead_exists(url):
                results.append({"url": url, "status": "already_exists", "public_id": public_id})
                continue

            from linkedin.db.crm_profiles import _get_lead_source
            clean_url = public_id_to_url(public_id)
            lead = Lead.objects.create(
                website=clean_url,
                owner=dept_user,
                department=campaign.department,
                lead_source=_get_lead_source(session),
            )
            results.append({"url": url, "status": "created", "public_id": public_id, "lead_id": lead.pk})

        return Response(results, status=status.HTTP_207_MULTI_STATUS)


class ProfileDetailView(APIView):
    authentication_classes = [ApiKeyAuthentication]
    permission_classes = [HasApiKey]

    def get(self, request, public_id: str):
        from crm.models import Lead
        clean_url = public_id_to_url(public_id)
        lead = Lead.objects.filter(website=clean_url).first()
        if not lead:
            return Response({"error": "Profile not found"}, status=status.HTTP_404_NOT_FOUND)
        return Response(_lead_to_dict(lead))
