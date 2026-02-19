# tests/test_api_urls.py
"""
URL resolution tests for the REST API routes.

Tests 1-9: Pure URL reversal — no DB access needed.
Test 10:   Integration test using Django test Client (requires DB for auth middleware).
"""
import pytest
from django.test import Client
from django.urls import resolve, reverse

from linkedin.rest_api.views.campaigns import CampaignDetailView, CampaignListView
from linkedin.rest_api.views.jobs import JobDetailView, JobListView, LaneTriggerView
from linkedin.rest_api.views.profiles import ProfileDetailView, ProfileListView
from linkedin.rest_api.views.webhooks import WebhookDetailView, WebhookListCreateView


# ---------------------------------------------------------------------------
# Profile URL resolution
# ---------------------------------------------------------------------------


def test_profile_list_url_resolves():
    url = reverse("rest_api:profile-list")
    resolved = resolve(url)
    assert resolved.func.view_class is ProfileListView


def test_profile_detail_url_resolves():
    url = reverse("rest_api:profile-detail", args=["some-public-id"])
    resolved = resolve(url)
    assert resolved.func.view_class is ProfileDetailView


# ---------------------------------------------------------------------------
# Campaign URL resolution
# ---------------------------------------------------------------------------


def test_campaign_list_url_resolves():
    url = reverse("rest_api:campaign-list")
    resolved = resolve(url)
    assert resolved.func.view_class is CampaignListView


def test_campaign_detail_url_resolves():
    url = reverse("rest_api:campaign-detail", args=[1])
    resolved = resolve(url)
    assert resolved.func.view_class is CampaignDetailView


# ---------------------------------------------------------------------------
# Lane + Job URL resolution
# ---------------------------------------------------------------------------


def test_lane_trigger_url_resolves():
    url = reverse("rest_api:lane-trigger", args=["search"])
    resolved = resolve(url)
    assert resolved.func.view_class is LaneTriggerView


def test_job_list_url_resolves():
    url = reverse("rest_api:job-list")
    resolved = resolve(url)
    assert resolved.func.view_class is JobListView


def test_job_detail_url_resolves():
    url = reverse("rest_api:job-detail", args=[1])
    resolved = resolve(url)
    assert resolved.func.view_class is JobDetailView


# ---------------------------------------------------------------------------
# Webhook URL resolution
# ---------------------------------------------------------------------------


def test_webhook_list_url_resolves():
    url = reverse("rest_api:webhook-list")
    resolved = resolve(url)
    assert resolved.func.view_class is WebhookListCreateView


def test_webhook_detail_url_resolves():
    url = reverse("rest_api:webhook-detail", args=[1])
    resolved = resolve(url)
    assert resolved.func.view_class is WebhookDetailView


# ---------------------------------------------------------------------------
# Integration: confirm /api/v1/ prefix is wired into the root URLconf
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_api_root_path_prefix():
    """GET /api/v1/profiles/ must return 401 or 403, NOT 404.

    A 404 would mean the URL was not found, i.e., the include() is missing.
    401/403 proves Django routed the request to ProfileListView (auth failed).
    """
    client = Client()
    response = client.get("/api/v1/profiles/")
    assert response.status_code in (401, 403), (
        f"Expected 401 or 403 (auth rejection) but got {response.status_code}. "
        "This likely means /api/v1/ is not wired into the root URLconf."
    )
