"""Async webhook dispatch — fire and forget via httpx."""
import datetime
import hashlib
import hmac
import ipaddress
import json
import logging
import socket
import threading
from urllib.parse import urlparse

import httpx

from linkedin.models import ActionJob, WebhookSubscription

logger = logging.getLogger(__name__)

# Networks that must never receive webhook deliveries (SSRF protection).
_BLOCKED_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),       # loopback
    ipaddress.ip_network("169.254.0.0/16"),    # link-local / AWS metadata
    ipaddress.ip_network("10.0.0.0/8"),        # RFC 1918
    ipaddress.ip_network("172.16.0.0/12"),     # RFC 1918
    ipaddress.ip_network("192.168.0.0/16"),    # RFC 1918
    ipaddress.ip_network("::1/128"),           # IPv6 loopback
    ipaddress.ip_network("fc00::/7"),          # IPv6 ULA
]


def _is_blocked_ip(ip_str: str) -> bool:
    """Return True if the IP address falls within any blocked network."""
    try:
        addr = ipaddress.ip_address(ip_str)
    except ValueError:
        return True  # Unparseable — block it
    return any(addr in net for net in _BLOCKED_NETWORKS)


def _url_is_safe(url: str) -> bool:
    """Resolve the URL's hostname and return False if it resolves to a blocked IP.

    Returns False (unsafe) on DNS resolution failure.
    """
    hostname = urlparse(url).hostname
    if not hostname:
        return False
    try:
        addr_infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        logger.warning("Webhook SSRF check: DNS resolution failed for %s: %s", hostname, exc)
        return False
    for addr_info in addr_infos:
        ip = addr_info[4][0]
        if _is_blocked_ip(ip):
            logger.warning(
                "Webhook SSRF check: blocked delivery to %s — resolved to private/reserved IP %s",
                url, ip,
            )
            return False
    return True


def dispatch_webhooks(event: str, job: ActionJob) -> "threading.Thread | None":
    """Fire webhook POST to matching active subscriptions (non-blocking).

    The DB query is performed on the calling thread to avoid ORM use from a
    daemon thread.  The actual HTTP delivery is dispatched to a daemon thread
    so the caller returns immediately.

    Returns the daemon Thread if any matching subscriptions exist, or None.

    Non-blocking: each delivery is attempted once; failures are logged, not raised.
    SSRF protection: each URL is checked against blocked IP ranges before delivery.
    HMAC signing: each POST includes X-OpenOutreach-Signature: sha256=<hmac_hex>.
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
        return None

    def _deliver():
        with httpx.Client(timeout=5.0) as client:
            for sub in matching:
                # SSRF guard: resolve and validate the destination IP.
                if not _url_is_safe(sub.url):
                    continue
                try:
                    sig = hmac.new(
                        sub.secret.encode(),
                        json.dumps(payload, sort_keys=True).encode(),
                        hashlib.sha256,
                    ).hexdigest()
                    headers = {"X-OpenOutreach-Signature": f"sha256={sig}"}
                    client.post(sub.url, json=payload, headers=headers)
                except Exception as exc:
                    logger.warning("Webhook delivery failed for %s: %s", sub.url, exc)

    thread = threading.Thread(target=_deliver, daemon=True)
    thread.start()
    return thread
