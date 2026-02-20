# tests/test_daemon_jobs.py
"""Tests for _process_action_jobs and _execute_action_job in linkedin/daemon.py."""
import datetime
from unittest.mock import ANY, MagicMock, call, patch

import pytest

from linkedin.daemon import _execute_action_job, _process_action_jobs
from linkedin.models import ActionJob


# ---------------------------------------------------------------------------
# 1. No pending jobs — function returns without side effects
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_process_action_jobs_no_pending(fake_session):
    """When no ActionJobs exist, _process_action_jobs returns without error."""
    # Ensure the table is empty
    ActionJob.objects.all().delete()

    # Should not raise
    _process_action_jobs(fake_session)

    # No jobs created as a side effect
    assert ActionJob.objects.count() == 0


# ---------------------------------------------------------------------------
# 2. Pending job → completed, result stored
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_process_action_jobs_marks_running_then_completed(fake_session):
    """A pending job becomes 'completed' with result after a successful execute."""
    job = ActionJob.objects.create(lane="search", campaign=fake_session.campaign)
    assert job.status == "pending"

    with patch("linkedin.daemon._execute_action_job", return_value={"profiles_found": 3}) as mock_exec:
        with patch("linkedin.rest_api.webhooks.dispatch_webhooks") as mock_dispatch:
            _process_action_jobs(fake_session)

    job.refresh_from_db()
    assert job.status == "completed"
    assert job.result == {"profiles_found": 3}

    # _execute_action_job must have been called with the session and the job
    mock_exec.assert_called_once_with(fake_session, job)

    # dispatch_webhooks must have been called with the completed event
    mock_dispatch.assert_called_once_with("job.completed", ANY)


# ---------------------------------------------------------------------------
# 3. Exception in execute → job marked failed, error key in result
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_process_action_jobs_marks_failed_on_exception(fake_session):
    """If _execute_action_job raises, the job status becomes 'failed' and result has 'error'."""
    job = ActionJob.objects.create(lane="connect", campaign=fake_session.campaign)

    with patch("linkedin.daemon._execute_action_job", side_effect=RuntimeError("boom")):
        with patch("linkedin.rest_api.webhooks.dispatch_webhooks") as mock_dispatch:
            _process_action_jobs(fake_session)

    job.refresh_from_db()
    assert job.status == "failed"
    assert "error" in job.result
    assert "boom" in job.result["error"]

    # dispatch_webhooks must have been called with the failed event
    mock_dispatch.assert_called_once_with("job.failed", ANY)


# ---------------------------------------------------------------------------
# 4. dispatch_webhooks is called with the right event and job
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_process_action_jobs_calls_dispatch_webhooks(fake_session):
    """dispatch_webhooks('job.completed', job) is called after a successful execute."""
    job = ActionJob.objects.create(lane="qualify", campaign=fake_session.campaign)

    # dispatch_webhooks is imported lazily inside _process_action_jobs, so patch
    # it at its source module rather than on linkedin.daemon.
    with patch("linkedin.daemon._execute_action_job", return_value={"ok": True}):
        with patch("linkedin.rest_api.webhooks.dispatch_webhooks") as mock_dispatch:
            _process_action_jobs(fake_session)

    # Reload to get the saved instance; the function passes the same object
    job.refresh_from_db()
    assert job.status == "completed"

    # dispatch_webhooks must have been called once with event="job.completed"
    assert mock_dispatch.call_count == 1
    event_arg, job_arg = mock_dispatch.call_args.args
    assert event_arg == "job.completed"
    assert job_arg.pk == job.pk


# ---------------------------------------------------------------------------
# 5. Oldest-first ordering — the job with the earliest created_at is processed
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_process_action_jobs_processes_oldest_first(fake_session):
    """When multiple pending jobs exist, the one with the earliest created_at is processed."""
    now = datetime.datetime.now(tz=datetime.timezone.utc)

    older_job = ActionJob.objects.create(lane="search", campaign=fake_session.campaign)
    newer_job = ActionJob.objects.create(lane="follow_up", campaign=fake_session.campaign)

    # Force created_at ordering (auto_now_add may set them the same in fast tests)
    ActionJob.objects.filter(pk=older_job.pk).update(
        created_at=now - datetime.timedelta(minutes=5)
    )
    ActionJob.objects.filter(pk=newer_job.pk).update(
        created_at=now
    )

    processed_jobs = []

    def fake_execute(session, job):
        processed_jobs.append(job.pk)
        return {"done": True}

    with patch("linkedin.daemon._execute_action_job", side_effect=fake_execute):
        with patch("linkedin.rest_api.webhooks.dispatch_webhooks") as mock_dispatch:
            _process_action_jobs(fake_session)

    assert len(processed_jobs) == 1
    assert processed_jobs[0] == older_job.pk

    older_job.refresh_from_db()
    newer_job.refresh_from_db()
    assert older_job.status == "completed"
    assert newer_job.status == "pending"

    # dispatch_webhooks must have been called once (for the older job)
    mock_dispatch.assert_called_once()


# ---------------------------------------------------------------------------
# 6. Unknown lane raises ValueError
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_execute_action_job_unknown_lane(fake_session):
    """_execute_action_job raises ValueError for an unrecognized lane."""
    job = ActionJob.objects.create(lane="connect", campaign=fake_session.campaign)
    # Bypass model validation by directly setting lane to an invalid value
    ActionJob.objects.filter(pk=job.pk).update(lane="invalid_lane")
    job.refresh_from_db()

    with pytest.raises(ValueError, match="Unknown lane"):
        _execute_action_job(fake_session, job)


# ---------------------------------------------------------------------------
# 7. M3: Null campaign guard — ValueError raised immediately
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_execute_action_job_null_campaign_raises(fake_session):
    """_execute_action_job raises ValueError when job has no campaign."""
    job = ActionJob.objects.create(lane="search", campaign=None)
    with pytest.raises(ValueError, match="no campaign"):
        _execute_action_job(fake_session, job)


# ---------------------------------------------------------------------------
# 8. Lane dispatch map — each known lane name calls correct execute()
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_execute_action_job_dispatches_to_correct_lane(fake_session):
    """_execute_action_job instantiates and calls the correct lane for each lane choice."""
    from unittest.mock import patch

    lane_module_map = {
        "connect": "linkedin.lanes.connect.ConnectLane",
        "check_pending": "linkedin.lanes.check_pending.CheckPendingLane",
        "follow_up": "linkedin.lanes.follow_up.FollowUpLane",
        "qualify": "linkedin.lanes.qualify.QualifyLane",
        "search": "linkedin.lanes.search.SearchLane",
    }

    for lane_name, cls_path in lane_module_map.items():
        job = ActionJob.objects.create(lane=lane_name, campaign=fake_session.campaign)

        with patch(f"{cls_path}.execute", return_value={"done": True}) as mock_execute:
            result = _execute_action_job(fake_session, job)
            assert mock_execute.called, f"execute() not called for lane {lane_name!r}"
            assert result == {"done": True}, f"Unexpected result for lane {lane_name!r}"


# ---------------------------------------------------------------------------
# 9. S2: job.params keyword forwarded to SearchLane.execute()
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_execute_action_job_forwards_keyword_to_search_lane(fake_session):
    """_execute_action_job forwards keyword param to SearchLane.execute()."""
    from unittest.mock import patch

    job = ActionJob.objects.create(
        lane="search",
        campaign=fake_session.campaign,
        params={"keyword": "Head of Growth SaaS"},
    )

    with patch("linkedin.lanes.search.SearchLane.execute", return_value={"profiles_found": 3}) as mock_exec:
        result = _execute_action_job(fake_session, job)
        mock_exec.assert_called_once_with(keyword="Head of Growth SaaS")
        assert result == {"profiles_found": 3}
