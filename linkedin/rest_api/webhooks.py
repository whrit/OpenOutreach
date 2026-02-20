"""Async webhook dispatch — fire and forget via httpx."""
import datetime
import logging
import threading

import httpx

from linkedin.models import ActionJob, WebhookSubscription

logger = logging.getLogger(__name__)


def dispatch_webhooks(event: str, job: ActionJob) -> None:
    """Fire webhook POST to matching active subscriptions (non-blocking).

    The DB query is performed on the calling thread to avoid ORM use from a
    daemon thread.  The actual HTTP delivery is dispatched to a daemon thread
    so the caller returns immediately.

    Non-blocking: each delivery is attempted once; failures are logged, not raised.
    """
    payload = {
        "event": event,
        "job_id": str(job.pk),
        "lane": job.lane,
        "campaign_id": job.campaign_id,
        "result": job.result,
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
    }

    # Perform the DB query on the calling thread before spawning.
    subscriptions = list(WebhookSubscription.objects.filter(active=True))
    # Narrow to subscriptions that listen to this event.
    matching = [s for s in subscriptions if event in s.events]
    # Narrow to subscriptions for this campaign (or global subscriptions with no campaign).
    if job.campaign_id:
        matching = [
            s for s in matching
            if s.campaign_id is None or s.campaign_id == job.campaign_id
        ]

    if not matching:
        return

    def _deliver():
        with httpx.Client(timeout=5.0) as client:
            for sub in matching:
                try:
                    client.post(sub.url, json=payload)
                except Exception as exc:
                    logger.warning("Webhook delivery failed for %s: %s", sub.url, exc)

    thread = threading.Thread(target=_deliver, daemon=True)
    thread.start()
