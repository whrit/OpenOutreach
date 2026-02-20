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


# ---------------------------------------------------------------------------
# Existing tests — updated for paginated response format
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_profile_list_empty(api_key, campaign):
    request = _make_request("get", api_key)
    view = ProfileListView.as_view()
    response = view(request)
    assert response.status_code == 200
    # Paginated response: check structure keys and that results is an empty list
    assert "count" in response.data
    assert "results" in response.data
    assert response.data["results"] == []


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
    # Paginated response: results key holds the list
    public_ids = [p["public_id"] for p in response.data["results"]]
    assert "state-filter-test" in public_ids


@pytest.mark.django_db
def test_profile_list_filter_by_campaign_id(api_key, campaign, fake_session):
    """?campaign_id=<id> must return only leads belonging to that campaign."""
    from crm.models import Lead
    from linkedin.db.crm_profiles import public_id_to_url, _get_lead_source

    # Create a lead associated with the campaign's department
    clean_url = public_id_to_url("campaign-filter-test")
    Lead.objects.create(
        website=clean_url,
        owner=fake_session.django_user,
        department=campaign.department,
        lead_source=_get_lead_source(fake_session),
    )

    request = _make_request("get", api_key, path=f"/?campaign_id={campaign.pk}")
    view = ProfileListView.as_view()
    response = view(request)
    assert response.status_code == 200
    # Paginated response: results key holds the list
    public_ids = [p["public_id"] for p in response.data["results"]]
    assert "campaign-filter-test" in public_ids


@pytest.mark.django_db
def test_profile_list_filter_campaign_id_non_integer(api_key, campaign):
    """?campaign_id=abc must return 400 with a descriptive error."""
    request = _make_request("get", api_key, path="/?campaign_id=abc")
    view = ProfileListView.as_view()
    response = view(request)
    assert response.status_code == 400
    assert response.data == {"error": "campaign_id must be an integer"}


# ---------------------------------------------------------------------------
# New pagination tests (A1)
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_profile_list_pagination_metadata(api_key, campaign):
    """Profile list response includes pagination metadata."""
    request = _make_request("get", api_key)
    view = ProfileListView.as_view()
    response = view(request)
    assert response.status_code == 200
    assert "count" in response.data
    assert "results" in response.data
    assert "next" in response.data
    assert "previous" in response.data
    assert isinstance(response.data["results"], list)


@pytest.mark.django_db
def test_profile_list_limit_offset(api_key, campaign, fake_session):
    """?limit and ?offset parameters control which profiles are returned."""
    from crm.models import Lead
    from linkedin.db.crm_profiles import public_id_to_url, _get_lead_source

    # Create 5 leads
    for i in range(5):
        Lead.objects.create(
            website=public_id_to_url(f"paginate-user-{i}"),
            owner=fake_session.django_user,
            department=campaign.department,
            lead_source=_get_lead_source(fake_session),
        )

    _, raw = ApiKey.generate("test-paginate")
    factory = APIRequestFactory()
    # Get first 2
    req1 = factory.get(
        "/profiles/",
        data={"limit": 2, "offset": 0},
        HTTP_AUTHORIZATION=f"Api-Key {raw}",
    )
    r1 = ProfileListView.as_view()(req1)
    assert r1.status_code == 200
    assert len(r1.data["results"]) == 2
    # count reflects total leads present (>= 5)
    assert r1.data["count"] >= 5


@pytest.mark.django_db
def test_profile_list_pagination_next_and_previous(api_key, campaign, fake_session):
    """next/previous URLs are set correctly based on offset position."""
    from crm.models import Lead
    from linkedin.db.crm_profiles import public_id_to_url, _get_lead_source

    for i in range(5):
        Lead.objects.create(
            website=public_id_to_url(f"nextprev-user-{i}"),
            owner=fake_session.django_user,
            department=campaign.department,
            lead_source=_get_lead_source(fake_session),
        )

    _, raw = ApiKey.generate("test-nextprev")
    factory = APIRequestFactory()

    # With limit=2, offset=2 there should be both next and previous
    req = factory.get(
        "/profiles/",
        data={"limit": 2, "offset": 2},
        HTTP_AUTHORIZATION=f"Api-Key {raw}",
    )
    r = ProfileListView.as_view()(req)
    assert r.status_code == 200
    # previous should exist since offset > 0
    assert r.data["previous"] is not None
    # count >= 5 means offset 2 + limit 2 = 4 which is < 5, so next should exist
    if r.data["count"] > 4:
        assert r.data["next"] is not None


@pytest.mark.django_db
def test_profile_list_invalid_limit(api_key, campaign):
    """?limit=abc returns 400."""
    request = _make_request("get", api_key, path="/?limit=abc")
    view = ProfileListView.as_view()
    response = view(request)
    assert response.status_code == 400
    assert "error" in response.data


@pytest.mark.django_db
def test_profile_list_invalid_offset(api_key, campaign):
    """?offset=xyz returns 400."""
    request = _make_request("get", api_key, path="/?offset=xyz")
    view = ProfileListView.as_view()
    response = view(request)
    assert response.status_code == 400
    assert "error" in response.data


# ---------------------------------------------------------------------------
# New test: happy-path profile detail
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_profile_detail_returns_existing_profile(fake_session):
    """GET /profiles/{public_id}/ returns correct data for an existing profile."""
    from crm.models import Lead
    from linkedin.db.crm_profiles import url_to_public_id, public_id_to_url
    from linkedin.rest_api.views.profiles import ProfileDetailView

    lead = Lead.objects.create(
        website="https://www.linkedin.com/in/happy-path-user/",
        owner=fake_session.django_user,
        department=fake_session.campaign.department,
        first_name="Alice",
        last_name="Smith",
    )
    public_id = url_to_public_id(lead.website)
    _, raw = ApiKey.generate("test-detail")
    factory = APIRequestFactory()
    request = factory.get(f"/profiles/{public_id}/", HTTP_AUTHORIZATION=f"Api-Key {raw}")
    response = ProfileDetailView.as_view()(request, public_id=public_id)
    assert response.status_code == 200
    assert response.data["public_id"] == public_id
    assert response.data["first_name"] == "Alice"
    assert response.data["last_name"] == "Smith"
    assert response.data["url"] == lead.website


# ---------------------------------------------------------------------------
# New test: inject with non-existent campaign_id
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_profile_inject_campaign_not_found(fake_session):
    """POST /profiles/ with non-existent campaign_id returns 404."""
    _, raw = ApiKey.generate("test-no-campaign")
    factory = APIRequestFactory()
    request = factory.post(
        "/profiles/",
        {"urls": ["https://www.linkedin.com/in/test-user/"], "campaign_id": 99999},
        format="json",
        HTTP_AUTHORIZATION=f"Api-Key {raw}",
    )
    response = ProfileListView.as_view()(request)
    assert response.status_code == 404
