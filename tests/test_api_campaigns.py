import pytest
from rest_framework.test import APIRequestFactory

from linkedin.models import ApiKey, Campaign
from linkedin.rest_api.views.campaigns import CampaignListView, CampaignDetailView


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
def test_campaign_list_requires_auth(campaign):
    """Unauthenticated GET /campaigns/ must return 401 or 403."""
    factory = APIRequestFactory()
    request = factory.get("/campaigns/")
    view = CampaignListView.as_view()
    response = view(request)
    assert response.status_code in (401, 403)


@pytest.mark.django_db
def test_campaign_list_returns_campaigns(api_key, campaign):
    """With a valid API key, GET /campaigns/ returns a list containing the test campaign."""
    request = _make_request("get", api_key, path="/campaigns/")
    view = CampaignListView.as_view()
    response = view(request)
    assert response.status_code == 200
    assert isinstance(response.data, list)
    ids = [c["id"] for c in response.data]
    assert campaign.pk in ids

    # Verify expected fields are present on the returned campaign entry
    entry = next(c for c in response.data if c["id"] == campaign.pk)
    assert "department_name" in entry
    assert "product_docs" in entry
    assert "campaign_objective" in entry
    assert "followup_template" in entry
    assert "booking_link" in entry
    assert "is_partner" in entry
    assert "action_fraction" in entry


@pytest.mark.django_db
def test_campaign_detail_returns_campaign(api_key, campaign):
    """GET /campaigns/{id}/ returns correct campaign data."""
    request = _make_request("get", api_key, path=f"/campaigns/{campaign.pk}/")
    view = CampaignDetailView.as_view()
    response = view(request, pk=campaign.pk)
    assert response.status_code == 200
    assert response.data["id"] == campaign.pk
    assert response.data["department_name"] == campaign.department.name
    assert "product_docs" in response.data
    assert "campaign_objective" in response.data
    assert "followup_template" in response.data
    assert "booking_link" in response.data
    assert "is_partner" in response.data
    assert "action_fraction" in response.data


@pytest.mark.django_db
def test_campaign_detail_not_found(api_key, campaign):
    """GET /campaigns/99999/ returns 404 when no such campaign exists."""
    request = _make_request("get", api_key, path="/campaigns/99999/")
    view = CampaignDetailView.as_view()
    response = view(request, pk=99999)
    assert response.status_code == 404


@pytest.mark.django_db
def test_campaign_patch_updates_fields(api_key, campaign):
    """PATCH /campaigns/{id}/ with product_docs and booking_link updates those fields."""
    new_product_docs = "Updated product documentation for testing."
    new_booking_link = "https://example.com/book-a-demo"
    data = {
        "product_docs": new_product_docs,
        "booking_link": new_booking_link,
    }
    request = _make_request("patch", api_key, path=f"/campaigns/{campaign.pk}/", data=data)
    view = CampaignDetailView.as_view()
    response = view(request, pk=campaign.pk)
    assert response.status_code == 200
    assert response.data["product_docs"] == new_product_docs
    assert response.data["booking_link"] == new_booking_link

    # Confirm the change was persisted to the database
    campaign.refresh_from_db()
    assert campaign.product_docs == new_product_docs
    assert campaign.booking_link == new_booking_link


@pytest.mark.django_db
def test_campaign_patch_not_found(api_key, campaign):
    """PATCH /campaigns/{nonexistent_pk}/ returns 404 when no such campaign exists."""
    nonexistent_pk = campaign.pk + 99999
    data = {"product_docs": "Should not matter"}
    request = _make_request("patch", api_key, path=f"/campaigns/{nonexistent_pk}/", data=data)
    view = CampaignDetailView.as_view()
    response = view(request, pk=nonexistent_pk)
    assert response.status_code == 404


@pytest.mark.django_db
def test_campaign_patch_no_patchable_fields(fake_session):
    """PATCH with only non-patchable fields returns 400."""
    campaign = fake_session.campaign
    _, raw = ApiKey.generate("test")
    factory = APIRequestFactory()
    request = factory.patch(
        f"/campaigns/{campaign.pk}/",
        {"is_partner": True, "action_fraction": 0.5},
        format="json",
        HTTP_AUTHORIZATION=f"Api-Key {raw}",
    )
    view = CampaignDetailView.as_view()
    response = view(request, pk=campaign.pk)
    assert response.status_code == 400
    assert "error" in response.data


@pytest.mark.django_db
def test_campaign_patch_ignores_readonly_fields(api_key, campaign):
    """PATCH attempt to change is_partner or action_fraction must NOT update those fields."""
    original_is_partner = campaign.is_partner
    original_action_fraction = campaign.action_fraction

    data = {
        "is_partner": not original_is_partner,
        "action_fraction": 0.42,
        "product_docs": "A legitimate update.",
    }
    request = _make_request("patch", api_key, path=f"/campaigns/{campaign.pk}/", data=data)
    view = CampaignDetailView.as_view()
    response = view(request, pk=campaign.pk)
    assert response.status_code == 200

    # Read-only fields must remain unchanged
    campaign.refresh_from_db()
    assert campaign.is_partner == original_is_partner
    assert campaign.action_fraction == original_action_fraction

    # The writable field should have been updated
    assert campaign.product_docs == "A legitimate update."
