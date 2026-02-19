# n8n Integration Design for OpenOutreach

**Date:** 2026-02-19
**Status:** Approved
**Approach:** Approach A — Full DRF REST API + n8n Community Node

---

## Overview

Add a REST API to OpenOutreach so that n8n workflows can orchestrate LinkedIn automations: inject leads into the pipeline, query CRM state, trigger lanes on-demand, manage campaign config, and receive webhook callbacks when jobs complete.

The integration is split into two phases:
1. **Phase 1** — REST API (usable immediately with n8n's generic HTTP Request node)
2. **Phase 2** — TypeScript n8n community node (`n8n-nodes-openoutreach`) published to npm

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                     n8n workflow                         │
│  ┌─────────────────────────────────────────────────┐    │
│  │  OpenOutreach node (TypeScript npm package)      │    │
│  │  - Resource: Profiles / Campaigns / Lanes / Jobs │    │
│  │  - Credential: base URL + API key               │    │
│  └──────────────────────────┬──────────────────────┘    │
└─────────────────────────────┼───────────────────────────┘
                              │ HTTPS + Api-Key header
                              ▼
┌─────────────────────────────────────────────────────────┐
│              OpenOutreach (Docker / server)              │
│                                                          │
│  ┌─────────────────────────────────────────────────┐    │
│  │  DRF REST API  /api/v1/...                       │    │
│  │  (Django + gunicorn, or runserver in dev)        │    │
│  └─────────────┬─────────────────┬─────────────────┘    │
│                │ writes          │ reads                  │
│                ▼                 ▼                        │
│  ┌──────────────────┐  ┌────────────────────────────┐   │
│  │  ActionJob table │  │  CRM tables (Lead, Deal,   │   │
│  │  (new model)     │  │   Contact, Campaign, etc.)  │   │
│  └────────┬─────────┘  └────────────────────────────┘   │
│           │ daemon polls                                   │
│           ▼                                               │
│  ┌────────────────────────────────────────────────────┐  │
│  │  Daemon loop (existing)                             │  │
│  │  — _process_action_jobs() called after each tick   │  │
│  │  — executes queued jobs using existing lane logic   │  │
│  │  — updates status + dispatches webhooks on done     │  │
│  └────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

**Core principle:** The daemon remains the single Playwright browser session owner. The REST API never calls the browser directly — it writes `ActionJob` rows and reads CRM tables. The daemon processes jobs between its existing lane ticks, preserving stealth, rate limiting, and session safety.

---

## Phase 1: REST API

### New Files

```
linkedin/
├── rest_api/                       # new Django app
│   ├── __init__.py
│   ├── apps.py
│   ├── authentication.py           # ApiKeyAuthentication (DRF)
│   ├── permissions.py              # HasApiKey permission class
│   ├── serializers.py              # DRF serializers
│   ├── views.py                    # DRF ViewSets
│   ├── urls.py                     # /api/v1/ URL conf
│   └── webhooks.py                 # dispatch_webhooks() helper
```

### New Models (added to `linkedin/models.py`)

```python
class ApiKey(models.Model):
    name       = CharField(max_length=200)
    key_hash   = CharField(max_length=64, unique=True)  # SHA-256 of raw key
    active     = BooleanField(default=True)
    created_at = DateTimeField(auto_now_add=True)

class ActionJob(models.Model):
    LANE_CHOICES = [
        ("connect", "Connect"),
        ("check_pending", "Check Pending"),
        ("follow_up", "Follow Up"),
        ("qualify", "Qualify"),
        ("search", "Search"),
    ]
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("running", "Running"),
        ("completed", "Completed"),
        ("failed", "Failed"),
    ]
    lane       = CharField(max_length=50, choices=LANE_CHOICES)
    params     = JSONField(default=dict)          # e.g. {"keyword": "CTO SaaS"}
    status     = CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    result     = JSONField(null=True, blank=True)
    campaign   = ForeignKey(Campaign, on_delete=CASCADE, null=True)
    created_at = DateTimeField(auto_now_add=True)
    updated_at = DateTimeField(auto_now=True)

class WebhookSubscription(models.Model):
    url      = URLField(max_length=500)
    events   = JSONField(default=list)   # ["job.completed", "job.failed", "profile.state_changed"]
    campaign = ForeignKey(Campaign, on_delete=CASCADE, null=True, blank=True)
    active   = BooleanField(default=True)
    created_at = DateTimeField(auto_now_add=True)
```

### API Endpoints

Base path: `/api/v1/`
Auth header: `Authorization: Api-Key <raw_token>`

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/profiles/` | List profiles; `?state=new\|pending\|connected\|completed\|enriched\|disqualified`, `?campaign_id=` |
| `POST` | `/profiles/` | Inject profile URL(s) → creates Lead(s) with url_only state |
| `GET` | `/profiles/{public_id}/` | Get state + data for one profile |
| `GET` | `/campaigns/` | List all campaigns |
| `GET` | `/campaigns/{id}/` | Get campaign config |
| `PATCH` | `/campaigns/{id}/` | Update `product_docs`, `campaign_objective`, `followup_template`, `booking_link` |
| `POST` | `/lanes/{lane}/trigger/` | Enqueue an ActionJob; body: `{"campaign_id": ..., "params": {...}}` |
| `GET` | `/jobs/` | List jobs; `?status=pending\|running\|completed\|failed` |
| `GET` | `/jobs/{id}/` | Poll a single job's status + result |
| `POST` | `/webhooks/` | Register a webhook URL |
| `DELETE` | `/webhooks/{id}/` | Unregister a webhook |

**Job trigger request/response:**
```json
// POST /api/v1/lanes/search/trigger/
{ "campaign_id": 1, "params": { "keyword": "Head of Growth SaaS" } }

// 202 Accepted
{ "job_id": "42", "status": "pending", "lane": "search", "campaign_id": 1 }
```

**Job poll response:**
```json
// GET /api/v1/jobs/42/
{
  "job_id": "42",
  "lane": "search",
  "status": "completed",
  "result": { "profiles_discovered": 8, "keyword": "Head of Growth SaaS" },
  "created_at": "2026-02-19T10:00:00Z",
  "updated_at": "2026-02-19T10:01:32Z"
}
```

### Webhook Payload

Delivered via `POST` to the registered URL using `httpx` (async, non-blocking):

```json
{
  "event": "job.completed",
  "job_id": "42",
  "lane": "search",
  "campaign_id": 1,
  "result": { "profiles_discovered": 8 },
  "timestamp": "2026-02-19T10:01:32Z"
}
```

Event types: `job.completed`, `job.failed`, `profile.state_changed`

### Daemon Changes

Add `_process_action_jobs(session)` called after each major tick in the daemon loop:

```python
def _process_action_jobs(session):
    """Execute one pending ActionJob per daemon tick."""
    job = ActionJob.objects.filter(status="pending").order_by("created_at").first()
    if not job:
        return
    job.status = "running"
    job.save()
    try:
        result = _execute_job(session, job)
        job.status = "completed"
        job.result = result
    except Exception as e:
        job.status = "failed"
        job.result = {"error": str(e)}
    finally:
        job.save()
        dispatch_webhooks("job." + job.status, job)
```

`_execute_job` maps `job.lane` to the corresponding lane's `execute()` method, setting `session.campaign` from `job.campaign` first.

### Authentication Flow

1. Admin creates an `ApiKey` via Django Admin (raw token shown once, then only hash stored)
2. n8n stores the raw token as a credential
3. Each API request includes `Authorization: Api-Key <raw_token>`
4. `ApiKeyAuthentication.authenticate()` hashes the incoming token, looks up the `ApiKey` row, and attaches the linked user to `request.user`

### Dependencies Added

- `djangorestframework` → `requirements/base.txt`
- `httpx` → `requirements/base.txt` (for webhook delivery; likely already present via langchain)

---

## Phase 2: n8n Community Node

### Package Layout

```
n8n-nodes-openoutreach/        # separate git repo / npm package
├── package.json
├── tsconfig.json
├── index.ts
├── credentials/
│   └── OpenOutreachApi.credentials.ts
└── nodes/
    └── OpenOutreach/
        ├── OpenOutreach.node.ts
        ├── OpenOutreach.node.json
        ├── openoutreach.svg
        └── actions/
            ├── index.ts
            ├── profiles.ts
            ├── campaigns.ts
            ├── lanes.ts
            ├── jobs.ts
            └── webhooks.ts
```

### Credentials (`OpenOutreachApi.credentials.ts`)

| Field | Type | Description |
|-------|------|-------------|
| `baseUrl` | string | e.g. `https://openoutreach.example.com` |
| `apiKey` | password | Raw API key token |

Authentication type: `apiKey` in header — `Authorization: Api-Key {{apiKey}}`

### Node Resources & Operations

**Profiles**
- `getMany` — GET /profiles/ with state + campaign filters
- `get` — GET /profiles/{publicId}/
- `inject` — POST /profiles/ (single URL or array)

**Campaigns**
- `getMany` — GET /campaigns/
- `get` — GET /campaigns/{id}/
- `update` — PATCH /campaigns/{id}/

**Lanes**
- `trigger` — POST /lanes/{lane}/trigger/ with campaign + params
  - `lane` field: dropdown (Connect / Check Pending / Follow Up / Qualify / Search)
  - `waitForCompletion` toggle: if on, polls GET /jobs/{id}/ until done (with configurable timeout)

**Jobs**
- `get` — GET /jobs/{id}/
- `getMany` — GET /jobs/ with status filter

**Webhooks**
- `register` — POST /webhooks/
- `delete` — DELETE /webhooks/{id}/

### `waitForCompletion` Pattern

When the user enables "Wait for completion" on a Lanes → Trigger operation, the node:
1. POSTs to trigger → gets `job_id`
2. Polls GET /jobs/{job_id}/ every 5s
3. Returns when `status == "completed"` or `"failed"`
4. Times out after configurable seconds (default: 300s)

This lets n8n workflows pause and branch on the result without needing a separate webhook setup.

---

## Deployment

### HTTPS (required for remote n8n)

Add a **Caddy** or **Nginx** reverse proxy to the Docker Compose stack:

```yaml
# local.yml addition
caddy:
  image: caddy:2
  ports: ["443:443", "80:80"]
  volumes:
    - ./Caddyfile:/etc/caddy/Caddyfile
    - caddy_data:/data
```

```
# Caddyfile
openoutreach.example.com {
  reverse_proxy openoutreach:8000
}
```

Alternatively, use a **Cloudflare Tunnel** for zero-config HTTPS without port-forwarding.

### Running the API

For production, add `gunicorn` to the compose service:
```bash
gunicorn linkedin.django_settings.wsgi:application --bind 0.0.0.0:8000 --workers 2
```

The daemon process and the API process both connect to the same SQLite DB (read-heavy API + write-heavy daemon → acceptable at this scale). For higher load, migrate to PostgreSQL.

---

## Implementation Sequence

### Phase 1 — REST API

1. Add `ApiKey`, `ActionJob`, `WebhookSubscription` models + migrations
2. Create `linkedin/rest_api/` app with DRF auth, serializers, views, URLs
3. Wire up `/api/v1/` in `linkedin/urls.py`
4. Add `_process_action_jobs()` + `dispatch_webhooks()` to `daemon.py`
5. Register new models in `admin.py`
6. Add `djangorestframework` + `httpx` to `requirements/base.txt`
7. Write tests for API endpoints

### Phase 2 — n8n Node

1. Initialize npm package with n8n community node boilerplate
2. Implement `OpenOutreachApi` credentials
3. Implement each resource's operations in `actions/`
4. Build main `OpenOutreach.node.ts`
5. Add `waitForCompletion` polling helper
6. Publish to npm as `n8n-nodes-openoutreach`
7. Document install steps for n8n (Settings → Community Nodes → install)

---

## Open Questions / Future Work

- **Concurrent API + daemon writes to SQLite** — fine at low scale; monitor for lock contention. Migrate to PostgreSQL if needed.
- **Webhook retry** — initial design is fire-and-forget. Add retry queue if delivery reliability matters.
- **Per-job rate limiting** — injected jobs bypass the daemon's normal timing. Consider adding a `min_job_interval` guard in `_process_action_jobs`.
- **n8n Trigger node** — a separate polling trigger node could start n8n workflows reactively (e.g., "when a profile reaches CONNECTED state"). Not in scope for Phase 1/2 but a natural Phase 3.
- **Search Keywords resource** — exposing `SearchKeyword` CRUD would let n8n inject specific keywords, bypassing the LLM. Also a good Phase 3 addition.
