import pytest
from linkedin.models import ActionJob, Campaign, WebhookSubscription
from linkedin.rest_api.serializers import (
    ProfileStateSerializer,
    ProfileInjectSerializer,
    CampaignSerializer,
    ActionJobSerializer,
    LaneTriggerSerializer,
    WebhookSerializer,
)
from common.models import Department


@pytest.fixture
def campaign(db):
    dept = Department.objects.create(name="Serializer Test Dept")
    return Campaign.objects.create(department=dept)


def test_profile_state_serializer_valid():
    data = {
        "public_id": "john-doe",
        "url": "https://www.linkedin.com/in/john-doe/",
        "state": "connected",
        "first_name": "John",
        "last_name": "Doe",
        "title": "CTO",
        "company": "Acme Corp",
    }
    ser = ProfileStateSerializer(data=data)
    assert ser.is_valid(), ser.errors


def test_profile_inject_serializer_valid(campaign):
    data = {
        "urls": ["https://www.linkedin.com/in/john-doe/"],
        "campaign_id": campaign.pk,
    }
    ser = ProfileInjectSerializer(data=data)
    assert ser.is_valid(), ser.errors


def test_profile_inject_serializer_requires_urls(campaign):
    data = {"campaign_id": campaign.pk}
    ser = ProfileInjectSerializer(data=data)
    assert not ser.is_valid()
    assert "urls" in ser.errors


def test_profile_inject_serializer_requires_campaign_id():
    data = {"urls": ["https://www.linkedin.com/in/john-doe/"]}
    ser = ProfileInjectSerializer(data=data)
    assert not ser.is_valid()
    assert "campaign_id" in ser.errors


def test_campaign_serializer_read(campaign):
    ser = CampaignSerializer(campaign)
    data = ser.data
    assert data["id"] == campaign.pk
    assert "product_docs" in data
    assert "campaign_objective" in data
    assert "department_name" in data


def test_campaign_serializer_partial_update(campaign):
    ser = CampaignSerializer(campaign, data={"product_docs": "new docs"}, partial=True)
    assert ser.is_valid(), ser.errors
    updated = ser.save()
    assert updated.product_docs == "new docs"


def test_action_job_serializer_read(campaign):
    job = ActionJob.objects.create(lane="search", campaign=campaign)
    ser = ActionJobSerializer(job)
    data = ser.data
    assert data["lane"] == "search"
    assert data["status"] == "pending"
    assert "id" in data


def test_lane_trigger_serializer_valid(campaign):
    data = {"lane": "search", "campaign_id": campaign.pk, "params": {"keyword": "CTO"}}
    ser = LaneTriggerSerializer(data=data)
    assert ser.is_valid(), ser.errors


def test_lane_trigger_serializer_invalid_lane(campaign):
    data = {"lane": "teleport", "campaign_id": campaign.pk}
    ser = LaneTriggerSerializer(data=data)
    assert not ser.is_valid()
    assert "lane" in ser.errors


def test_webhook_serializer_read(campaign):
    ws = WebhookSubscription.objects.create(
        url="https://example.com/hook",
        events=["job.completed"],
        campaign=campaign,
    )
    ser = WebhookSerializer(ws)
    data = ser.data
    assert data["url"] == "https://example.com/hook"
    assert data["events"] == ["job.completed"]
    assert data["active"] is True
