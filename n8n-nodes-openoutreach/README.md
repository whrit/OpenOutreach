# n8n-nodes-openoutreach

An [n8n](https://n8n.io) community node for [OpenOutreach](https://github.com/eracle/openoutreach) — a self-hosted LinkedIn automation tool for B2B lead generation.

[![License: GPL-3.0](https://img.shields.io/badge/License-GPL%20v3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)

---

## Supported Resources

| Resource | Operations |
|---|---|
| **Profiles** | Get Many (with filters + pagination), Get (by public ID), Inject (bulk URL import) |
| **Campaigns** | Get Many, Get, Update |
| **Lanes** | Trigger (check_pending, connect, follow_up, qualify, search) |
| **Jobs** | Get, Get Many (with status filter + pagination) |
| **Webhooks** | Register, Delete |

---

## Prerequisites

- n8n ≥ 1.0.0
- A running OpenOutreach instance (Docker or local)
- An OpenOutreach API key (see below)

---

## Installation

### In n8n Cloud or self-hosted n8n

1. Open n8n → **Settings → Community Nodes**
2. Click **Install**
3. Enter `n8n-nodes-openoutreach` and confirm
4. Restart n8n if prompted

### For local development (linked package)

```bash
# In this repo
cd n8n-nodes-openoutreach
npm install
npm run build

# In your n8n custom extensions directory
npm link /path/to/openoutreach/n8n-nodes-openoutreach
```

---

## Creating an API Key

1. Start OpenOutreach and open Django Admin: `http://localhost:8000/admin/`
2. Log in with your superuser credentials
3. Navigate to **Linkedin → Api keys → Add Api Key**
4. Enter a name (e.g. `n8n`) and click **Save**
5. Copy the raw key shown in the confirmation banner — it is only displayed once

---

## Configuring the Credential

1. In n8n, open **Settings → Credentials → New Credential**
2. Search for **OpenOutreach API** and select it
3. Fill in:
   - **Base URL** — the URL of your OpenOutreach instance, e.g. `https://openoutreach.yourdomain.com` or `http://localhost:8000` for local dev
   - **API Key** — the raw key copied from Django Admin
4. Click **Save** — n8n will test the connection automatically

---

## Basic Workflow Examples

### 1. Inject leads and trigger a connect run

```
[Manual trigger]
  → OpenOutreach: Profiles → Inject
      Profile URLs: ["https://www.linkedin.com/in/john-doe/"]
      Campaign ID: 1
  → OpenOutreach: Lanes → Trigger
      Lane: connect
      Campaign ID: 1
      Wait for Completion: false
```

### 2. Poll until a lane job finishes

```
[Manual trigger]
  → OpenOutreach: Lanes → Trigger
      Lane: qualify
      Campaign ID: 1
      Wait for Completion: true
      Timeout (Seconds): 300
  → [Continue workflow with job result]
```

### 3. List recent completed profiles

```
[Schedule trigger — every hour]
  → OpenOutreach: Profiles → Get Many
      State Filter: Completed
      Campaign ID: 1
      Return All: false
      Limit: 100
  → [Send to CRM / Google Sheets / Slack]
```

### 4. Register a webhook for job completion events

```
[Manual trigger]
  → OpenOutreach: Webhooks → Register
      URL: https://your-n8n.yourdomain.com/webhook/openoutreach
      Events: job.completed, job.failed
      Campaign ID: 1
```

---

## HTTPS Setup (for remote n8n → self-hosted OpenOutreach)

The n8n credential requires an HTTPS URL when n8n is cloud-hosted or on a remote server. Two options:

### Option A: Caddy reverse proxy (recommended)

The repository ships a `Caddyfile` and `local.yml` with a ready-to-use Caddy service. Edit `Caddyfile` to replace the placeholder domain, then:

```bash
docker compose -f local.yml up -d
```

Caddy will obtain and renew a Let's Encrypt TLS certificate automatically.

### Option B: Cloudflare Tunnel (no port-forwarding required)

```bash
cloudflared tunnel login
cloudflared tunnel create openoutreach
cloudflared tunnel route dns openoutreach openoutreach.yourdomain.com
cloudflared tunnel run --url http://localhost:8000 openoutreach
```

---

## Compatibility

- n8n-workflow peer dependency: `>=1.0.0 <3`
- Tested against n8n 1.x

---

## Resources

- [OpenOutreach repository](https://github.com/eracle/openoutreach)
- [n8n community nodes documentation](https://docs.n8n.io/integrations/community-nodes/)

---

## License

GPL-3.0 — see [LICENCE.md](../LICENCE.md)
