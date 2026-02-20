import pytest
from rest_framework.test import APIRequestFactory
from linkedin.models import ApiKey
from linkedin.rest_api.views.campaigns import CampaignListView


@pytest.mark.django_db
def test_throttle_allows_normal_requests(fake_session):
    """A normal number of requests (well under limit) should succeed."""
    _, raw = ApiKey.generate("test")
    factory = APIRequestFactory()
    for _ in range(5):
        request = factory.get("/campaigns/", HTTP_AUTHORIZATION=f"Api-Key {raw}")
        view = CampaignListView.as_view()
        response = view(request)
        assert response.status_code == 200
