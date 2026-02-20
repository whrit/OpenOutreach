import os

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from linkedin.models import ActionJob, Campaign
from linkedin.rest_api.authentication import ApiKeyAuthentication
from linkedin.rest_api.permissions import HasApiKey
from linkedin.rest_api.serializers import ActionJobSerializer, LaneTriggerSerializer

_VALID_LANES = [choice[0] for choice in ActionJob.LANE_CHOICES]
VALID_STATUSES = {choice[0] for choice in ActionJob.STATUS_CHOICES}

_MAX_PENDING_JOBS = int(os.environ.get("MAX_PENDING_JOBS", "50"))


class LaneTriggerView(APIView):
    """
    POST /lanes/{lane}/trigger/ — create an ActionJob in pending status.

    Returns 202 Accepted with job_id, status, lane, and campaign_id.
    Returns 400 if lane is invalid or params exceed size limit.
    Returns 404 if campaign_id does not exist.
    Returns 429 if the pending job queue is full.
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

        # Check queue capacity before creating a new job
        pending_count = ActionJob.objects.filter(status="pending").count()
        if pending_count >= _MAX_PENDING_JOBS:
            return Response(
                {
                    "error": (
                        f"Job queue is full ({pending_count} pending jobs). "
                        "Wait for existing jobs to complete before triggering new ones."
                    )
                },
                status=status.HTTP_429_TOO_MANY_REQUESTS,
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
            headers={"Location": f"/api/v1/jobs/{job.pk}/"},
        )


class JobListView(APIView):
    """
    GET /jobs/ — list all ActionJobs with limit/offset pagination,
    optionally filtered by ?status=.
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

        # Pagination
        try:
            limit = min(int(request.query_params.get("limit", 100)), 1000)
            offset = max(int(request.query_params.get("offset", 0)), 0)
        except (ValueError, TypeError):
            return Response(
                {"error": "limit and offset must be integers"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        total_count = qs.count()
        page_qs = qs[offset: offset + limit]

        results = [ActionJobSerializer(job).data for job in page_qs]

        # Build next/previous URLs
        base_path = request.build_absolute_uri(request.path)

        def _page_url(new_offset):
            params = request.query_params.copy()
            params["offset"] = new_offset
            params["limit"] = limit
            return f"{base_path}?{'&'.join(f'{k}={v}' for k, v in params.items())}"

        next_url = _page_url(offset + limit) if offset + limit < total_count else None
        prev_url = _page_url(max(offset - limit, 0)) if offset > 0 else None

        return Response({
            "count": total_count,
            "next": next_url,
            "previous": prev_url,
            "results": results,
        })


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

        return Response(ActionJobSerializer(job).data)
