from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from linkedin.models import ActionJob, Campaign
from linkedin.rest_api.authentication import ApiKeyAuthentication
from linkedin.rest_api.permissions import HasApiKey
from linkedin.rest_api.serializers import ActionJobSerializer, LaneTriggerSerializer

_VALID_LANES = [choice[0] for choice in ActionJob.LANE_CHOICES]
VALID_STATUSES = {choice[0] for choice in ActionJob.STATUS_CHOICES}


class LaneTriggerView(APIView):
    """
    POST /lanes/{lane}/trigger/ — create an ActionJob in pending status.

    Returns 202 Accepted with job_id, status, lane, and campaign_id.
    Returns 400 if lane is invalid.
    Returns 404 if campaign_id does not exist.
    """

    authentication_classes = [ApiKeyAuthentication]
    permission_classes = [HasApiKey]

    def post(self, request, lane: str):
        # Validate the lane from the URL before running the body serializer,
        # so that an invalid lane always yields a 400 regardless of the body.
        if lane not in _VALID_LANES:
            return Response(
                {"error": f"Invalid lane '{lane}'. Valid choices: {_VALID_LANES}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Inject the lane from the URL so the serializer can validate it too.
        data = dict(request.data)
        data["lane"] = lane
        serializer = LaneTriggerSerializer(data=data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        campaign_id = serializer.validated_data["campaign_id"]
        try:
            campaign = Campaign.objects.get(pk=campaign_id)
        except Campaign.DoesNotExist:
            return Response(
                {"error": f"Campaign {campaign_id} not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        job = ActionJob.objects.create(
            lane=lane,
            params=serializer.validated_data.get("params", {}),
            status="pending",
            campaign=campaign,
        )

        return Response(
            {
                "job_id": str(job.pk),
                "status": job.status,
                "lane": job.lane,
                "campaign_id": job.campaign_id,
            },
            status=status.HTTP_202_ACCEPTED,
        )


class JobListView(APIView):
    """
    GET /jobs/ — list all ActionJobs, optionally filtered by ?status=.
    """

    authentication_classes = [ApiKeyAuthentication]
    permission_classes = [HasApiKey]

    def get(self, request):
        qs = ActionJob.objects.all()

        status_filter = request.query_params.get("status")
        if status_filter is not None:
            if status_filter not in VALID_STATUSES:
                return Response(
                    {"error": f"Invalid status. Valid values: {sorted(VALID_STATUSES)}"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            qs = qs.filter(status=status_filter)

        serializer = ActionJobSerializer(qs, many=True)

        # Rename the 'id' field to 'job_id' (string) in the response to match
        # the contract without modifying the shared serializer definition.
        data = []
        for item in serializer.data:
            entry = dict(item)
            entry["job_id"] = str(entry.pop("id"))
            data.append(entry)

        return Response(data)


class JobDetailView(APIView):
    """
    GET /jobs/{id}/ — retrieve a single ActionJob by primary key.
    """

    authentication_classes = [ApiKeyAuthentication]
    permission_classes = [HasApiKey]

    def get(self, request, pk: int):
        try:
            job = ActionJob.objects.get(pk=pk)
        except ActionJob.DoesNotExist:
            return Response({"error": "Job not found"}, status=status.HTTP_404_NOT_FOUND)

        serializer = ActionJobSerializer(job)
        data = dict(serializer.data)
        data["job_id"] = str(data.pop("id"))
        return Response(data)
