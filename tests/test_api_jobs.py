import pytest
from rest_framework.test import APIRequestFactory

from linkedin.models import ActionJob, ApiKey, Campaign
from linkedin.rest_api.views.jobs import JobDetailView, JobListView, LaneTriggerView


@pytest.fixture
def api_key(db):
    obj, raw = ApiKey.generate("test-key")
    return obj, raw


@pytest.fixture
def campaign(fake_session):
    return fake_session.campaign


def _make_request(method, api_key_tuple, path="/", data=None, **kwargs):
    """Helper: create an authenticated request via Api-Key header."""
    obj, raw = api_key_tuple
    auth_header = f"Api-Key {raw}"
    factory = APIRequestFactory()
    req_fn = getattr(factory, method)
    if data is not None:
        request = req_fn(
            path, data=data, format="json",
            HTTP_AUTHORIZATION=auth_header, **kwargs
        )
    else:
        request = req_fn(path, HTTP_AUTHORIZATION=auth_header, **kwargs)
    return request


# ---------------------------------------------------------------------------
# LaneTriggerView tests
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_lane_trigger_creates_job(api_key, campaign):
    """POST valid body returns 202, creates job with status=pending."""
    data = {"campaign_id": campaign.pk, "params": {"keyword": "Head of Growth SaaS"}}
    request = _make_request("post", api_key, path="/lanes/search/trigger/", data=data)
    view = LaneTriggerView.as_view()
    response = view(request, lane="search")

    assert response.status_code == 202
    assert response.data["status"] == "pending"
    assert response.data["lane"] == "search"
    assert response.data["campaign_id"] == campaign.pk
    assert "job_id" in response.data

    # Confirm the job exists in the DB
    job_id = int(response.data["job_id"])
    job = ActionJob.objects.get(pk=job_id)
    assert job.status == "pending"
    assert job.lane == "search"
    assert job.campaign_id == campaign.pk
    assert job.params == {"keyword": "Head of Growth SaaS"}


@pytest.mark.django_db
def test_lane_trigger_invalid_lane(api_key, campaign):
    """POST to an invalid lane returns 400."""
    data = {"campaign_id": campaign.pk}
    request = _make_request("post", api_key, path="/lanes/invalid_lane/trigger/", data=data)
    view = LaneTriggerView.as_view()
    response = view(request, lane="invalid_lane")

    assert response.status_code == 400


@pytest.mark.django_db
def test_lane_trigger_campaign_not_found(api_key, campaign):
    """POST with a non-existent campaign_id returns 404."""
    data = {"campaign_id": 99999}
    request = _make_request("post", api_key, path="/lanes/connect/trigger/", data=data)
    view = LaneTriggerView.as_view()
    response = view(request, lane="connect")

    assert response.status_code == 404


@pytest.mark.django_db
def test_lane_trigger_requires_auth(campaign):
    """Unauthenticated POST must return 401 or 403."""
    factory = APIRequestFactory()
    request = factory.post(
        "/lanes/connect/trigger/",
        data={"campaign_id": campaign.pk},
        format="json",
    )
    view = LaneTriggerView.as_view()
    response = view(request, lane="connect")

    assert response.status_code in (401, 403)


@pytest.mark.django_db
def test_lane_trigger_params_optional(api_key, campaign):
    """POST without params field succeeds and defaults params to {}."""
    data = {"campaign_id": campaign.pk}
    request = _make_request("post", api_key, path="/lanes/qualify/trigger/", data=data)
    view = LaneTriggerView.as_view()
    response = view(request, lane="qualify")

    assert response.status_code == 202
    job_id = int(response.data["job_id"])
    job = ActionJob.objects.get(pk=job_id)
    assert job.params == {}


# ---------------------------------------------------------------------------
# JobListView tests
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_job_list_all(api_key, campaign):
    """GET /jobs/ returns 200 with a list (may be empty)."""
    request = _make_request("get", api_key, path="/jobs/")
    view = JobListView.as_view()
    response = view(request)

    assert response.status_code == 200
    assert isinstance(response.data, list)


@pytest.mark.django_db
def test_job_list_filter_by_status(api_key, campaign):
    """GET /jobs/?status=pending returns only pending jobs."""
    # Create two pending jobs
    job1 = ActionJob.objects.create(lane="connect", campaign=campaign, status="pending")
    job2 = ActionJob.objects.create(lane="follow_up", campaign=campaign, status="pending")
    # Create one completed job
    job3 = ActionJob.objects.create(lane="qualify", campaign=campaign, status="completed")

    request = _make_request("get", api_key, path="/jobs/", data={"status": "pending"})
    view = JobListView.as_view()
    response = view(request)

    assert response.status_code == 200
    returned_ids = [int(j["job_id"]) for j in response.data]
    assert job1.pk in returned_ids
    assert job2.pk in returned_ids
    assert job3.pk not in returned_ids


@pytest.mark.django_db
def test_job_list_invalid_status(fake_session):
    """?status=invalid_value returns 400."""
    _, raw = ApiKey.generate("test")
    factory = APIRequestFactory()
    request = factory.get("/jobs/", data={"status": "bogus"}, HTTP_AUTHORIZATION=f"Api-Key {raw}")
    view = JobListView.as_view()
    response = view(request)
    assert response.status_code == 400
    assert "error" in response.data


@pytest.mark.django_db
def test_job_list_requires_auth(campaign):
    """Unauthenticated GET /jobs/ must return 401 or 403."""
    factory = APIRequestFactory()
    request = factory.get("/jobs/")
    view = JobListView.as_view()
    response = view(request)

    assert response.status_code in (401, 403)


# ---------------------------------------------------------------------------
# JobDetailView tests
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_job_detail_found(api_key, campaign):
    """GET /jobs/{id}/ returns 200 with correct fields."""
    job = ActionJob.objects.create(lane="check_pending", campaign=campaign, status="running")

    request = _make_request("get", api_key, path=f"/jobs/{job.pk}/")
    view = JobDetailView.as_view()
    response = view(request, pk=job.pk)

    assert response.status_code == 200
    assert response.data["job_id"] == str(job.pk)
    assert response.data["lane"] == "check_pending"
    assert response.data["status"] == "running"
    assert response.data["campaign_id"] == campaign.pk
    assert "result" in response.data
    assert "created_at" in response.data
    assert "updated_at" in response.data


@pytest.mark.django_db
def test_job_detail_not_found(api_key, campaign):
    """GET /jobs/99999/ returns 404 when no such job exists."""
    request = _make_request("get", api_key, path="/jobs/99999/")
    view = JobDetailView.as_view()
    response = view(request, pk=99999)

    assert response.status_code == 404
