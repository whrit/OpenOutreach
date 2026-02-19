import pytest
from rest_framework.test import APIRequestFactory

from linkedin.models import ApiKey, Campaign
from linkedin.rest_api.views.profiles import ProfileListView, ProfileDetailView
from common.models import Department


@pytest.fixture
def api_key(db):
    obj, raw = ApiKey.generate("test-key")
    return obj, raw


@pytest.fixture
def campaign(fake_session):
    return fake_session.campaign


def _make_request(method, api_key_tuple, path="/", data=None, **kwargs):
    """Helper: create a request authenticated via Api-Key header."""
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


@pytest.mark.django_db
def test_profile_list_empty(api_key, campaign):
    request = _make_request("get", api_key)
    view = ProfileListView.as_view()
    response = view(request)
    assert response.status_code == 200
    assert response.data == []


@pytest.mark.django_db
def test_profile_list_requires_auth(campaign):
    factory = APIRequestFactory()
    request = factory.get("/")
    view = ProfileListView.as_view()
    response = view(request)
    # DRF returns 401 (not 403) when no auth header is present and an authenticator
    # with authenticate_header() is configured — this is standard DRF behavior.
    assert response.status_code in (401, 403)


@pytest.mark.django_db
def test_profile_inject_creates_lead(api_key, campaign, fake_session):
    data = {
        "urls": ["https://www.linkedin.com/in/test-inject-user/"],
        "campaign_id": campaign.pk,
    }
    request = _make_request("post", api_key, data=data)
    view = ProfileListView.as_view()
    response = view(request)
    assert response.status_code == 207
    results = response.data
    assert len(results) == 1
    assert results[0]["status"] == "created"
    assert results[0]["public_id"] == "test-inject-user"


@pytest.mark.django_db
def test_profile_inject_invalid_url(api_key, campaign):
    data = {
        "urls": ["not-a-url"],
        "campaign_id": campaign.pk,
    }
    request = _make_request("post", api_key, data=data)
    view = ProfileListView.as_view()
    response = view(request)
    assert response.status_code == 400


@pytest.mark.django_db
def test_profile_inject_duplicate_returns_already_exists(api_key, campaign, fake_session):
    url = "https://www.linkedin.com/in/duplicate-person/"
    data = {"urls": [url], "campaign_id": campaign.pk}
    request = _make_request("post", api_key, data=data)
    view = ProfileListView.as_view()
    # First inject
    view(request)
    # Second inject (same URL)
    request2 = _make_request("post", api_key, data=data)
    response2 = view(request2)
    assert response2.status_code == 207
    assert response2.data[0]["status"] == "already_exists"


@pytest.mark.django_db
def test_profile_detail_not_found(api_key, campaign):
    request = _make_request("get", api_key)
    view = ProfileDetailView.as_view()
    response = view(request, public_id="nonexistent-person")
    assert response.status_code == 404


@pytest.mark.django_db
def test_profile_list_filter_by_state(api_key, campaign, fake_session):
    # Inject a profile first
    from crm.models import Lead
    from linkedin.db.crm_profiles import public_id_to_url, _get_lead_source
    clean_url = public_id_to_url("state-filter-test")
    Lead.objects.create(
        website=clean_url,
        owner=fake_session.django_user,
        department=campaign.department,
        lead_source=_get_lead_source(fake_session),
    )
    # Filter by url_only state — pass query string via path
    request = _make_request("get", api_key, path="/?state=url_only")
    view = ProfileListView.as_view()
    response = view(request)
    assert response.status_code == 200
    public_ids = [p["public_id"] for p in response.data]
    assert "state-filter-test" in public_ids
