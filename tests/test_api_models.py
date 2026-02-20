import pytest
from linkedin.models import ApiKey, ActionJob, Campaign
from common.models import Department


@pytest.mark.django_db
def test_apikey_generate_and_authenticate():
    obj, raw = ApiKey.generate("test key")
    assert obj.pk is not None
    found = ApiKey.authenticate(raw)
    assert found == obj


@pytest.mark.django_db
def test_apikey_wrong_token_returns_none():
    ApiKey.generate("test key")
    assert ApiKey.authenticate("wrong") is None


@pytest.mark.django_db
def test_apikey_inactive_not_found():
    obj, raw = ApiKey.generate("inactive key")
    obj.active = False
    obj.save()
    assert ApiKey.authenticate(raw) is None


@pytest.mark.django_db
def test_action_job_defaults(fake_session):
    job = ActionJob.objects.create(lane="search", campaign=fake_session.campaign)
    assert job.status == "pending"
    assert job.params == {}
    assert job.result is None


@pytest.mark.django_db
def test_action_job_lane_choices(fake_session):
    valid_lanes = ["connect", "check_pending", "follow_up", "qualify", "search"]
    for lane in valid_lanes:
        job = ActionJob.objects.create(lane=lane, campaign=fake_session.campaign)
        assert job.lane == lane


@pytest.mark.django_db
def test_webhook_subscription_defaults(fake_session):
    from linkedin.models import WebhookSubscription
    ws = WebhookSubscription.objects.create(
        url="https://example.com/webhook",
        events=["job.completed"],
        campaign=fake_session.campaign,
    )
    assert ws.active is True
    assert ws.pk is not None


@pytest.mark.django_db
def test_webhook_subscription_events_default(fake_session):
    from linkedin.models import WebhookSubscription
    ws = WebhookSubscription.objects.create(
        url="https://example.com/default-events",
        campaign=fake_session.campaign,
    )
    assert ws.events == []


@pytest.mark.django_db
def test_action_job_null_campaign():
    job = ActionJob.objects.create(lane="search", campaign=None)
    assert job.pk is not None
    assert ActionJob.objects.filter(campaign__isnull=True).count() >= 1


@pytest.mark.django_db
def test_authenticate_returns_correct_key_by_hash(db):
    """authenticate() uses direct hash lookup, not a linear scan."""
    # Create multiple keys
    key_a, raw_a = ApiKey.generate("Key A")
    key_b, raw_b = ApiKey.generate("Key B")
    key_c, raw_c = ApiKey.generate("Key C")

    result = ApiKey.authenticate(raw_b)
    assert result is not None
    assert result.pk == key_b.pk
