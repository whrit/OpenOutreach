"""Tests for webhook register/delete views and dispatch helper."""
import hashlib
import hmac
import json
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
def test_webhook_create_returns_secret_on_creation(api_key, campaign):
    """POST valid body → 201, response includes the secret field."""
    data = {
        "url": "https://my-n8n.example.com/webhook/secret-test",
        "events": ["job.completed"],
        "campaign_id": campaign.pk,
    }
    request = _authed_request("post", api_key, path="/webhooks/", data=data)
    view = WebhookListCreateView.as_view()
    response = view(request)

    assert response.status_code == 201
    # Secret must be present and non-empty
    assert "secret" in response.data
    secret = response.data["secret"]
    assert secret and len(secret) > 0
    # Should match the DB value
    sub = WebhookSubscription.objects.get(url=data["url"])
    assert sub.secret == secret


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
        "events": ["job.completed"],
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
# dispatch_webhooks — unit tests (thread.join for determinism)
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
        thread = dispatch_webhooks("job.completed", job)
        if thread:
            thread.join(timeout=2)

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
        thread = dispatch_webhooks("job.completed", job)
        if thread:
            thread.join(timeout=2)

    mock_client_instance.post.assert_not_called()


@pytest.mark.django_db
def test_dispatch_webhooks_ignores_different_campaign(fake_session):
    """A subscription scoped to campaign A should not fire when the job belongs to campaign B."""
    from common.models import Department
    from django.contrib.auth.models import Group

    # Create a second campaign by creating a new Department (Django CRM uses MTI).
    group_b, _ = Group.objects.get_or_create(name="CampaignB-Group")
    dept_b, _ = Department.objects.get_or_create(id=group_b.id, defaults={"name": "CampaignB-Group"})
    campaign_b, _ = Campaign.objects.get_or_create(department=dept_b)

    campaign_a = fake_session.campaign

    # Subscription tied to campaign_b.
    WebhookSubscription.objects.create(
        url="https://example.com/hook-b",
        events=["job.completed"],
        campaign=campaign_b,
        active=True,
    )

    # Job for campaign_a — subscription for campaign_b should NOT fire.
    job = ActionJob.objects.create(
        lane="search",
        campaign=campaign_a,
    )

    mock_client_instance = MagicMock()
    mock_client_cls = MagicMock(return_value=mock_client_instance)
    mock_client_instance.__enter__ = MagicMock(return_value=mock_client_instance)
    mock_client_instance.__exit__ = MagicMock(return_value=False)

    with patch("linkedin.rest_api.webhooks.httpx.Client", mock_client_cls):
        from linkedin.rest_api.webhooks import dispatch_webhooks
        thread = dispatch_webhooks("job.completed", job)
        if thread:
            thread.join(timeout=2)

    mock_client_instance.post.assert_not_called()


# ---------------------------------------------------------------------------
# dispatch_webhooks — HMAC signature tests (M2)
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_dispatch_webhooks_sends_hmac_signature(campaign):
    """dispatch_webhooks must include X-OpenOutreach-Signature header with valid HMAC-SHA256."""
    sub = WebhookSubscription.objects.create(
        url="https://example.com/signed-hook",
        events=["job.completed"],
        campaign=campaign,
        active=True,
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
        thread = dispatch_webhooks("job.completed", job)
        if thread:
            thread.join(timeout=2)

    mock_client_instance.post.assert_called_once()
    call_kwargs = mock_client_instance.post.call_args
    headers = call_kwargs[1]["headers"]
    assert "X-OpenOutreach-Signature" in headers

    # Verify the HMAC is correct
    payload = call_kwargs[1]["json"]
    expected_sig = hmac.new(
        sub.secret.encode(),
        json.dumps(payload, sort_keys=True).encode(),
        hashlib.sha256,
    ).hexdigest()
    assert headers["X-OpenOutreach-Signature"] == f"sha256={expected_sig}"


# ---------------------------------------------------------------------------
# dispatch_webhooks — SSRF protection tests (C1)
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_dispatch_webhooks_blocks_loopback_url(campaign):
    """dispatch_webhooks must not POST to loopback addresses (127.x.x.x)."""
    WebhookSubscription.objects.create(
        url="http://127.0.0.1:8080/internal",
        events=["job.completed"],
        campaign=campaign,
        active=True,
    )
    job = ActionJob.objects.create(lane="connect", campaign=campaign)

    mock_client_instance = MagicMock()
    mock_client_cls = MagicMock(return_value=mock_client_instance)
    mock_client_instance.__enter__ = MagicMock(return_value=mock_client_instance)
    mock_client_instance.__exit__ = MagicMock(return_value=False)

    with patch("linkedin.rest_api.webhooks.httpx.Client", mock_client_cls):
        from linkedin.rest_api.webhooks import dispatch_webhooks
        thread = dispatch_webhooks("job.completed", job)
        if thread:
            thread.join(timeout=2)

    mock_client_instance.post.assert_not_called()


@pytest.mark.django_db
def test_dispatch_webhooks_blocks_link_local_url(campaign):
    """dispatch_webhooks must not POST to link-local/AWS metadata addresses (169.254.x.x)."""
    WebhookSubscription.objects.create(
        url="http://169.254.169.254/latest/meta-data/",
        events=["job.completed"],
        campaign=campaign,
        active=True,
    )
    job = ActionJob.objects.create(lane="connect", campaign=campaign)

    mock_client_instance = MagicMock()
    mock_client_cls = MagicMock(return_value=mock_client_instance)
    mock_client_instance.__enter__ = MagicMock(return_value=mock_client_instance)
    mock_client_instance.__exit__ = MagicMock(return_value=False)

    with patch("linkedin.rest_api.webhooks.httpx.Client", mock_client_cls):
        from linkedin.rest_api.webhooks import dispatch_webhooks
        thread = dispatch_webhooks("job.completed", job)
        if thread:
            thread.join(timeout=2)

    mock_client_instance.post.assert_not_called()


@pytest.mark.django_db
def test_dispatch_webhooks_blocks_private_rfc1918_url(campaign):
    """dispatch_webhooks must not POST to RFC 1918 private addresses (10.x, 172.16-31.x, 192.168.x)."""
    for private_url in [
        "http://10.0.0.1/hook",
        "http://172.16.0.1/hook",
        "http://192.168.1.1/hook",
    ]:
        WebhookSubscription.objects.create(
            url=private_url,
            events=["job.completed"],
            campaign=campaign,
            active=True,
        )

    job = ActionJob.objects.create(lane="connect", campaign=campaign)

    mock_client_instance = MagicMock()
    mock_client_cls = MagicMock(return_value=mock_client_instance)
    mock_client_instance.__enter__ = MagicMock(return_value=mock_client_instance)
    mock_client_instance.__exit__ = MagicMock(return_value=False)

    with patch("linkedin.rest_api.webhooks.httpx.Client", mock_client_cls):
        from linkedin.rest_api.webhooks import dispatch_webhooks
        thread = dispatch_webhooks("job.completed", job)
        if thread:
            thread.join(timeout=2)

    mock_client_instance.post.assert_not_called()


@pytest.mark.django_db
def test_dispatch_webhooks_allows_public_url(campaign):
    """dispatch_webhooks must POST to legitimate public URLs (not blocked by SSRF guard)."""
    sub = WebhookSubscription.objects.create(
        url="https://example.com/hook",
        events=["job.completed"],
        campaign=campaign,
        active=True,
    )
    job = ActionJob.objects.create(lane="connect", campaign=campaign)

    mock_client_instance = MagicMock()
    mock_client_cls = MagicMock(return_value=mock_client_instance)
    mock_client_instance.__enter__ = MagicMock(return_value=mock_client_instance)
    mock_client_instance.__exit__ = MagicMock(return_value=False)

    # Patch socket.getaddrinfo to return a predictable public IP
    import socket
    fake_addr_info = [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("93.184.216.34", 443))]

    with patch("linkedin.rest_api.webhooks.httpx.Client", mock_client_cls), \
         patch("linkedin.rest_api.webhooks.socket.getaddrinfo", return_value=fake_addr_info):
        from linkedin.rest_api.webhooks import dispatch_webhooks
        thread = dispatch_webhooks("job.completed", job)
        if thread:
            thread.join(timeout=2)

    mock_client_instance.post.assert_called_once()
    assert mock_client_instance.post.call_args[0][0] == sub.url


@pytest.mark.django_db
def test_dispatch_webhooks_blocks_dns_resolving_to_private(campaign):
    """dispatch_webhooks blocks URLs whose hostname resolves to a private IP."""
    import socket

    WebhookSubscription.objects.create(
        url="http://evil-internal.attacker.com/hook",
        events=["job.completed"],
        campaign=campaign,
        active=True,
    )
    job = ActionJob.objects.create(lane="connect", campaign=campaign)

    mock_client_instance = MagicMock()
    mock_client_cls = MagicMock(return_value=mock_client_instance)
    mock_client_instance.__enter__ = MagicMock(return_value=mock_client_instance)
    mock_client_instance.__exit__ = MagicMock(return_value=False)

    # Simulate DNS rebinding: hostname resolves to a private IP
    fake_addr_info = [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("10.0.0.1", 80))]

    with patch("linkedin.rest_api.webhooks.httpx.Client", mock_client_cls), \
         patch("linkedin.rest_api.webhooks.socket.getaddrinfo", return_value=fake_addr_info):
        from linkedin.rest_api.webhooks import dispatch_webhooks
        thread = dispatch_webhooks("job.completed", job)
        if thread:
            thread.join(timeout=2)

    mock_client_instance.post.assert_not_called()


@pytest.mark.django_db
def test_dispatch_webhooks_skips_on_dns_failure(campaign):
    """dispatch_webhooks logs warning and skips delivery when DNS resolution fails."""
    import socket

    WebhookSubscription.objects.create(
        url="http://nonexistent-host.invalid/hook",
        events=["job.completed"],
        campaign=campaign,
        active=True,
    )
    job = ActionJob.objects.create(lane="connect", campaign=campaign)

    mock_client_instance = MagicMock()
    mock_client_cls = MagicMock(return_value=mock_client_instance)
    mock_client_instance.__enter__ = MagicMock(return_value=mock_client_instance)
    mock_client_instance.__exit__ = MagicMock(return_value=False)

    with patch("linkedin.rest_api.webhooks.httpx.Client", mock_client_cls), \
         patch("linkedin.rest_api.webhooks.socket.getaddrinfo", side_effect=socket.gaierror("DNS failure")):
        from linkedin.rest_api.webhooks import dispatch_webhooks
        thread = dispatch_webhooks("job.completed", job)
        if thread:
            thread.join(timeout=2)

    mock_client_instance.post.assert_not_called()


# ---------------------------------------------------------------------------
# dispatch_webhooks — returns Thread object
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_dispatch_webhooks_returns_thread_when_matching(campaign):
    """dispatch_webhooks must return a threading.Thread when there are matching subscriptions."""
    import threading

    WebhookSubscription.objects.create(
        url="https://example.com/hook",
        events=["job.completed"],
        campaign=campaign,
        active=True,
    )
    job = ActionJob.objects.create(lane="connect", campaign=campaign)

    mock_client_instance = MagicMock()
    mock_client_cls = MagicMock(return_value=mock_client_instance)
    mock_client_instance.__enter__ = MagicMock(return_value=mock_client_instance)
    mock_client_instance.__exit__ = MagicMock(return_value=False)

    with patch("linkedin.rest_api.webhooks.httpx.Client", mock_client_cls):
        from linkedin.rest_api.webhooks import dispatch_webhooks
        result = dispatch_webhooks("job.completed", job)

    assert isinstance(result, threading.Thread)
    result.join(timeout=2)


@pytest.mark.django_db
def test_dispatch_webhooks_returns_none_when_no_match(campaign):
    """dispatch_webhooks must return None when there are no matching subscriptions."""
    # No subscriptions created
    job = ActionJob.objects.create(lane="connect", campaign=campaign)

    from linkedin.rest_api.webhooks import dispatch_webhooks
    result = dispatch_webhooks("job.completed", job)

    assert result is None


# ---------------------------------------------------------------------------
# dispatch_webhooks — global subscription (campaign=None) fires for any campaign
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_dispatch_webhooks_global_subscription_fires_for_any_campaign(fake_session):
    """A WebhookSubscription with campaign=None fires for jobs from ANY campaign."""
    from common.models import Department
    from django.contrib.auth.models import Group

    # Create a specific campaign for the job
    group_c, _ = Group.objects.get_or_create(name="CampaignC-Group")
    dept_c, _ = Department.objects.get_or_create(id=group_c.id, defaults={"name": "CampaignC-Group"})
    campaign_c, _ = Campaign.objects.get_or_create(department=dept_c)

    # Global subscription — no campaign filter
    sub = WebhookSubscription.objects.create(
        url="https://example.com/global-hook",
        events=["job.completed"],
        campaign=None,
        active=True,
    )

    job = ActionJob.objects.create(
        lane="connect",
        campaign=campaign_c,
    )

    mock_client_instance = MagicMock()
    mock_client_cls = MagicMock(return_value=mock_client_instance)
    mock_client_instance.__enter__ = MagicMock(return_value=mock_client_instance)
    mock_client_instance.__exit__ = MagicMock(return_value=False)

    with patch("linkedin.rest_api.webhooks.httpx.Client", mock_client_cls):
        from linkedin.rest_api.webhooks import dispatch_webhooks
        thread = dispatch_webhooks("job.completed", job)
        if thread:
            thread.join(timeout=2)

    mock_client_instance.post.assert_called_once()
    assert mock_client_instance.post.call_args[0][0] == sub.url
