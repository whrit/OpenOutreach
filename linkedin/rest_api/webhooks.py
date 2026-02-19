"""Async webhook dispatch — fire and forget via httpx."""
import datetime
import logging

import httpx

from linkedin.models import ActionJob, WebhookSubscription

logger = logging.getLogger(__name__)


def dispatch_webhooks(event: str, job: ActionJob) -> None:
    """
    Fire webhook POST to all active subscriptions matching `event` and
    (optionally) `job.campaign`.

    Non-blocking: each delivery is attempted once; failures are logged, not raised.
    """
    payload = {
        "event": event,
        "job_id": str(job.pk),
        "lane": job.lane,
        "campaign_id": job.campaign_id,
        "result": job.result,
        "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
    }

    subscriptions = WebhookSubscription.objects.filter(active=True)
    # Narrow to subscriptions that listen to this event
    matching = [s for s in subscriptions if event in s.events]
    # Narrow to subscriptions for this campaign (or global subscriptions with no campaign)
    if job.campaign_id:
        matching = [
            s for s in matching
            if s.campaign_id is None or s.campaign_id == job.campaign_id
        ]

    for sub in matching:
        try:
            with httpx.Client(timeout=5.0) as client:
                client.post(sub.url, json=payload)
        except Exception as exc:
            logger.warning("Webhook delivery failed for %s: %s", sub.url, exc)
