"""Tests for webhook register/delete views and dispatch helper."""
import pytest
from unittest.mock import patch, MagicMock
from rest_framework.test import APIRequestFactory

from linkedin.models import ActionJob, ApiKey, Campaign, WebhookSubscription
from linkedin.rest_api.views.webhooks import WebhookDetailView, WebhookListCreateView


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def api_key(db):
    obj, raw = ApiKey.generate("test-key")
    return obj, raw


@pytest.fixture
def campaign(fake_session):
    return fake_session.campaign


def _authed_request(method, api_key_tuple, path="/", data=None, **kwargs):
    """Create an APIRequestFactory request with Api-Key auth header."""
    _obj, raw = api_key_tuple
    auth_header = f"Api-Key {raw}"
    factory = APIRequestFactory()
    req_fn = getattr(factory, method)
    if data is not None:
        return req_fn(path, data=data, format="json", HTTP_AUTHORIZATION=auth_header, **kwargs)
    return req_fn(path, HTTP_AUTHORIZATION=auth_header, **kwargs)


# ---------------------------------------------------------------------------
# GET /webhooks/ — list
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_webhook_list_requires_auth():
    """Unauthenticated GET /webhooks/ must return 401 or 403."""
    factory = APIRequestFactory()
    request = factory.get("/webhooks/")
    view = WebhookListCreateView.as_view()
    response = view(request)
    assert response.status_code in (401, 403)


@pytest.mark.django_db
def test_webhook_list_empty(api_key):
    """Authenticated GET on empty DB returns 200 and an empty list."""
    request = _authed_request("get", api_key, path="/webhooks/")
    view = WebhookListCreateView.as_view()
    response = view(request)
    assert response.status_code == 200
    assert response.data == []


# ---------------------------------------------------------------------------
# POST /webhooks/ — create
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_webhook_create_valid(api_key, campaign):
    """POST valid body → 201, subscription persisted in DB."""
    data = {
        "url": "https://my-n8n.example.com/webhook/abc123",
        "events": ["job.completed", "job.failed"],
        "campaign_id": campaign.pk,
    }
    request = _authed_request("post", api_key, path="/webhooks/", data=data)
    view = WebhookListCreateView.as_view()
    response = view(request)

    assert response.status_code == 201
    assert response.data["url"] == data["url"]
    assert set(response.data["events"]) == {"job.completed", "job.failed"}
    assert response.data["campaign_id"] == campaign.pk

    # Verify persisted to DB
    assert WebhookSubscription.objects.filter(url=data["url"]).exists()


@pytest.mark.django_db
def test_webhook_create_invalid_url(api_key, campaign):
    """POST with a bad url → 400."""
    data = {
        "url": "not-a-valid-url",
        "events": ["job.completed"],
        "campaign_id": campaign.pk,
    }
    request = _authed_request("post", api_key, path="/webhooks/", data=data)
    view = WebhookListCreateView.as_view()
    response = view(request)
    assert response.status_code == 400


@pytest.mark.django_db
def test_webhook_create_invalid_event(api_key, campaign):
    """POST with an unrecognised event name → 400."""
    data = {
        "url": "https://example.com/hook",
        "events": ["invalid.event"],
        "campaign_id": campaign.pk,
    }
    request = _authed_request("post", api_key, path="/webhooks/", data=data)
    view = WebhookListCreateView.as_view()
    response = view(request)
    assert response.status_code == 400


@pytest.mark.django_db
def test_webhook_create_campaign_not_found(api_key):
    """POST with a non-existent campaign_id → 404."""
    data = {
        "url": "https://example.com/hook",
        "events": ["job.completed"],
        "campaign_id": 999999,
    }
    request = _authed_request("post", api_key, path="/webhooks/", data=data)
    view = WebhookListCreateView.as_view()
    response = view(request)
    assert response.status_code == 404


@pytest.mark.django_db
def test_webhook_create_no_campaign(api_key):
    """POST without campaign_id → 201, campaign field is null."""
    data = {
        "url": "https://example.com/hook",
        "events": ["profile.state_changed"],
    }
    request = _authed_request("post", api_key, path="/webhooks/", data=data)
    view = WebhookListCreateView.as_view()
    response = view(request)
    assert response.status_code == 201
    assert response.data["campaign_id"] is None

    sub = WebhookSubscription.objects.get(url=data["url"])
    assert sub.campaign is None


# ---------------------------------------------------------------------------
# DELETE /webhooks/{id}/ — delete
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_webhook_delete_valid(api_key, campaign):
    """DELETE existing webhook → 204, object removed from DB."""
    sub = WebhookSubscription.objects.create(
        url="https://example.com/hook-to-delete",
        events=["job.completed"],
        campaign=campaign,
    )
    request = _authed_request("delete", api_key, path=f"/webhooks/{sub.pk}/")
    view = WebhookDetailView.as_view()
    response = view(request, pk=sub.pk)
    assert response.status_code == 204
    assert not WebhookSubscription.objects.filter(pk=sub.pk).exists()


@pytest.mark.django_db
def test_webhook_delete_not_found(api_key):
    """DELETE non-existent webhook → 404."""
    request = _authed_request("delete", api_key, path="/webhooks/999999/")
    view = WebhookDetailView.as_view()
    response = view(request, pk=999999)
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# dispatch_webhooks — unit tests
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_dispatch_webhooks_delivers_to_matching_subscription(campaign):
    """dispatch_webhooks POSTs to active subscriptions that match the event."""
    sub = WebhookSubscription.objects.create(
        url="https://example.com/hook",
        events=["job.completed"],
        campaign=campaign,
        active=True,
    )
    job = ActionJob.objects.create(
        lane="connect",
        status="completed",
        result={"profiles_processed": 1},
        campaign=campaign,
    )

    mock_client_instance = MagicMock()
    mock_client_cls = MagicMock(return_value=mock_client_instance)
    mock_client_instance.__enter__ = MagicMock(return_value=mock_client_instance)
    mock_client_instance.__exit__ = MagicMock(return_value=False)

    with patch("linkedin.rest_api.webhooks.httpx.Client", mock_client_cls):
        from linkedin.rest_api.webhooks import dispatch_webhooks
        dispatch_webhooks("job.completed", job)

    mock_client_instance.post.assert_called_once()
    call_kwargs = mock_client_instance.post.call_args
    # First positional arg is the URL
    assert call_kwargs[0][0] == sub.url
    payload = call_kwargs[1]["json"]
    assert payload["event"] == "job.completed"
    assert payload["job_id"] == str(job.pk)
    assert payload["lane"] == "connect"
    assert payload["campaign_id"] == campaign.pk


@pytest.mark.django_db
def test_dispatch_webhooks_skips_inactive_subscription(campaign):
    """Inactive subscriptions are not called by dispatch_webhooks."""
    WebhookSubscription.objects.create(
        url="https://example.com/inactive-hook",
        events=["job.completed"],
        campaign=campaign,
        active=False,
    )
    job = ActionJob.objects.create(
        lane="connect",
        status="completed",
        result=None,
        campaign=campaign,
    )

    mock_client_instance = MagicMock()
    mock_client_cls = MagicMock(return_value=mock_client_instance)
    mock_client_instance.__enter__ = MagicMock(return_value=mock_client_instance)
    mock_client_instance.__exit__ = MagicMock(return_value=False)

    with patch("linkedin.rest_api.webhooks.httpx.Client", mock_client_cls):
        from linkedin.rest_api.webhooks import dispatch_webhooks
        dispatch_webhooks("job.completed", job)

    mock_client_instance.post.assert_not_called()
