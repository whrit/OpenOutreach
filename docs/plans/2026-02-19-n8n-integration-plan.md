# n8n Integration Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a DRF REST API to OpenOutreach (with ApiKey auth, async ActionJob queue, and webhook delivery) plus a TypeScript n8n community node (`n8n-nodes-openoutreach`) so n8n workflows can orchestrate LinkedIn automations.

**Architecture:** A new `linkedin/rest_api/` Django app exposes `/api/v1/` endpoints. Lane triggers write `ActionJob` rows; the daemon's loop picks them up after each tick and executes them using existing lane code. Webhooks are dispatched via `httpx` when jobs complete. The n8n node is a standalone TypeScript npm package that wraps the API with a typed UI, credential vault, and optional polling for job completion.

**Tech Stack:** Django REST Framework, httpx, TypeScript, n8n community node SDK (`n8n-workflow`), pytest

**Design doc:** `docs/plans/2026-02-19-n8n-node-design.md`

---

## Context You Must Know

- **Existing `linkedin/api/`** — this is the internal Voyager API client (NOT a REST API). Do not touch it. The new REST API lives in `linkedin/rest_api/`.
- **`AccountSession`** — central session object holding the Playwright browser. Only the daemon should use it. The REST API only reads/writes DB — never touches the browser.
- **`ActionJob`** — the async bridge. API writes jobs; daemon reads + executes them. This preserves stealth and rate limiting.
- **`linkedin/urls.py`** — already wires `/crm/` and `/admin/`. We add `/api/v1/` here.
- **`linkedin/models.py`** — add new models here (ApiKey, ActionJob, WebhookSubscription).
- **`requirements/base.txt`** — add DRF and httpx here (used by both local dev and Docker).
- **`make test`** runs pytest. Tests live in `tests/`.

---

## Phase 1: REST API

---

### Task 1: Add Models

**Files:**
- Modify: `linkedin/models.py`
- Create: `linkedin/migrations/0005_api_models.py` (auto-generated)

**Step 1: Add models to `linkedin/models.py`**

Append after the existing `SearchKeyword` class:

```python
import hashlib
import secrets


class ApiKey(models.Model):
    """API key for REST API authentication. Raw key shown once; stored as SHA-256 hash."""
    name = models.CharField(max_length=200)
    key_hash = models.CharField(max_length=64, unique=True)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "linkedin"

    def __str__(self):
        return self.name

    @classmethod
    def generate(cls, name: str) -> tuple["ApiKey", str]:
        """Create a new ApiKey. Returns (instance, raw_token). Store raw_token yourself."""
        raw = secrets.token_hex(32)
        key_hash = hashlib.sha256(raw.encode()).hexdigest()
        obj = cls.objects.create(name=name, key_hash=key_hash)
        return obj, raw

    @classmethod
    def authenticate(cls, raw_token: str) -> "ApiKey | None":
        key_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        return cls.objects.filter(key_hash=key_hash, active=True).first()


class ActionJob(models.Model):
    """Async bridge between the REST API and the daemon's browser session."""
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
    lane = models.CharField(max_length=50, choices=LANE_CHOICES)
    params = models.JSONField(default=dict)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    result = models.JSONField(null=True, blank=True)
    campaign = models.ForeignKey(
        Campaign, on_delete=models.CASCADE, null=True, blank=True,
        related_name="action_jobs",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "linkedin"
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.lane} [{self.status}]"


class WebhookSubscription(models.Model):
    """n8n (or any HTTP) endpoint to notify when jobs complete."""
    url = models.URLField(max_length=500)
    events = models.JSONField(default=list)  # ["job.completed", "job.failed", "profile.state_changed"]
    campaign = models.ForeignKey(
        Campaign, on_delete=models.CASCADE, null=True, blank=True,
        related_name="webhook_subscriptions",
    )
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "linkedin"

    def __str__(self):
        return self.url
```

**Step 2: Generate and run the migration**

```bash
python manage.py makemigrations linkedin --name api_models
python manage.py migrate
```

Expected: migration file created + applied without errors.

**Step 3: Write tests**

Create `tests/test_api_models.py`:

```python
import pytest
from linkedin.models import ApiKey, ActionJob, Campaign


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
def test_action_job_defaults():
    # Need a campaign; use existing fixture or create minimal one
    from common.models import Department
    dept = Department.objects.create(name="Test Dept")
    campaign = Campaign.objects.create(department=dept)
    job = ActionJob.objects.create(lane="search", campaign=campaign)
    assert job.status == "pending"
    assert job.params == {}
```

**Step 4: Run tests**

```bash
pytest tests/test_api_models.py -v
```

Expected: 3 PASS.

**Step 5: Commit**

```bash
git add linkedin/models.py linkedin/migrations/0005_api_models.py tests/test_api_models.py
git commit -m "feat: add ApiKey, ActionJob, WebhookSubscription models"
```

---

### Task 2: Add djangorestframework + httpx to requirements

**Files:**
- Modify: `requirements/base.txt`

**Step 1: Add dependencies**

Open `requirements/base.txt` and add:

```
djangorestframework>=3.15,<4
httpx>=0.27,<1
```

(Check if `httpx` is already present — langchain pulls it in. If so, skip adding it explicitly.)

**Step 2: Install locally**

```bash
uv pip install -r requirements/base.txt
```

Expected: installs without errors.

**Step 3: Add DRF to INSTALLED_APPS**

In `linkedin/django_settings.py`, find the `INSTALLED_APPS` list and add:

```python
"rest_framework",
"linkedin.rest_api",
```

**Step 4: Commit**

```bash
git add requirements/base.txt linkedin/django_settings.py
git commit -m "feat: add djangorestframework and httpx dependencies"
```

---

### Task 3: Create `linkedin/rest_api/` app scaffold

**Files:**
- Create: `linkedin/rest_api/__init__.py`
- Create: `linkedin/rest_api/apps.py`
- Create: `linkedin/rest_api/authentication.py`
- Create: `linkedin/rest_api/permissions.py`

**Step 1: Create `linkedin/rest_api/__init__.py`**

```python
# linkedin/rest_api/__init__.py
```

**Step 2: Create `linkedin/rest_api/apps.py`**

```python
from django.apps import AppConfig


class RestApiConfig(AppConfig):
    name = "linkedin.rest_api"
    label = "rest_api"
    verbose_name = "REST API"
```

**Step 3: Create `linkedin/rest_api/authentication.py`**

```python
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed

from linkedin.models import ApiKey


class ApiKeyAuthentication(BaseAuthentication):
    """Authenticate via 'Authorization: Api-Key <raw_token>' header."""

    def authenticate(self, request):
        auth_header = request.META.get("HTTP_AUTHORIZATION", "")
        if not auth_header.startswith("Api-Key "):
            return None  # Try next authenticator

        raw_token = auth_header[len("Api-Key "):]
        api_key = ApiKey.authenticate(raw_token)
        if not api_key:
            raise AuthenticationFailed("Invalid or inactive API key.")

        # DRF expects (user, token). We return (None, api_key) — views use request.auth.
        # To avoid Django auth issues, return a sentinel user.
        from django.contrib.auth.models import AnonymousUser
        return (AnonymousUser(), api_key)

    def authenticate_header(self, request):
        return "Api-Key"
```

**Step 4: Create `linkedin/rest_api/permissions.py`**

```python
from rest_framework.permissions import BasePermission


class HasApiKey(BasePermission):
    """Allow any request authenticated via ApiKeyAuthentication."""

    def has_permission(self, request, view):
        return request.auth is not None
```

**Step 5: Write tests**

Create `tests/test_api_auth.py`:

```python
import pytest
from rest_framework.test import APIRequestFactory

from linkedin.models import ApiKey
from linkedin.rest_api.authentication import ApiKeyAuthentication
from rest_framework.exceptions import AuthenticationFailed


@pytest.mark.django_db
def test_valid_api_key_authenticates():
    _, raw = ApiKey.generate("test")
    factory = APIRequestFactory()
    request = factory.get("/", HTTP_AUTHORIZATION=f"Api-Key {raw}")
    auth = ApiKeyAuthentication()
    user, key = auth.authenticate(request)
    assert key is not None


@pytest.mark.django_db
def test_invalid_api_key_raises():
    factory = APIRequestFactory()
    request = factory.get("/", HTTP_AUTHORIZATION="Api-Key badtoken")
    auth = ApiKeyAuthentication()
    with pytest.raises(AuthenticationFailed):
        auth.authenticate(request)


def test_missing_header_returns_none():
    factory = APIRequestFactory()
    request = factory.get("/")
    auth = ApiKeyAuthentication()
    assert auth.authenticate(request) is None
```

**Step 6: Run tests**

```bash
pytest tests/test_api_auth.py -v
```

Expected: 3 PASS.

**Step 7: Commit**

```bash
git add linkedin/rest_api/ tests/test_api_auth.py
git commit -m "feat: add REST API app scaffold with ApiKey authentication"
```

---

### Task 4: Serializers

**Files:**
- Create: `linkedin/rest_api/serializers.py`

**Step 1: Create `linkedin/rest_api/serializers.py`**

```python
from rest_framework import serializers

from linkedin.models import ActionJob, Campaign, WebhookSubscription


class ProfileStateSerializer(serializers.Serializer):
    """Read-only profile summary returned from CRM queries."""
    public_id = serializers.CharField()
    url = serializers.CharField()
    state = serializers.CharField()
    first_name = serializers.CharField(allow_blank=True)
    last_name = serializers.CharField(allow_blank=True)
    title = serializers.CharField(allow_blank=True)
    company = serializers.CharField(allow_blank=True)


class ProfileInjectSerializer(serializers.Serializer):
    """Inject one or more LinkedIn profile URLs into the pipeline."""
    urls = serializers.ListField(
        child=serializers.URLField(),
        min_length=1,
        max_length=100,
    )
    campaign_id = serializers.IntegerField()


class CampaignSerializer(serializers.ModelSerializer):
    department_name = serializers.CharField(source="department.name", read_only=True)

    class Meta:
        model = Campaign
        fields = [
            "id", "department_name", "product_docs", "campaign_objective",
            "followup_template", "booking_link", "is_partner", "action_fraction",
        ]
        read_only_fields = ["id", "department_name", "is_partner", "action_fraction"]


class ActionJobSerializer(serializers.ModelSerializer):
    class Meta:
        model = ActionJob
        fields = ["id", "lane", "params", "status", "result", "campaign_id", "created_at", "updated_at"]
        read_only_fields = ["id", "status", "result", "created_at", "updated_at"]


class LaneTriggerSerializer(serializers.Serializer):
    LANE_CHOICES = [c[0] for c in ActionJob.LANE_CHOICES]
    lane = serializers.ChoiceField(choices=LANE_CHOICES)
    campaign_id = serializers.IntegerField()
    params = serializers.DictField(default=dict)


class WebhookSerializer(serializers.ModelSerializer):
    class Meta:
        model = WebhookSubscription
        fields = ["id", "url", "events", "campaign_id", "active", "created_at"]
        read_only_fields = ["id", "created_at"]
```

**Step 2: Commit**

```bash
git add linkedin/rest_api/serializers.py
git commit -m "feat: add DRF serializers for profiles, campaigns, jobs, webhooks"
```

---

### Task 5: Profile Views (CRM reads + injection)

**Files:**
- Create: `linkedin/rest_api/views/profiles.py`

**Step 1: Create directory + `__init__.py`**

```bash
mkdir -p linkedin/rest_api/views
touch linkedin/rest_api/views/__init__.py
```

**Step 2: Create `linkedin/rest_api/views/profiles.py`**

```python
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from linkedin.db.crm_profiles import (
    url_to_public_id, public_id_to_url, lead_exists, create_enriched_lead,
)
from linkedin.rest_api.authentication import ApiKeyAuthentication
from linkedin.rest_api.permissions import HasApiKey
from linkedin.rest_api.serializers import ProfileInjectSerializer


def _lead_to_dict(lead):
    import json
    from linkedin.db.crm_profiles import url_to_public_id
    public_id = url_to_public_id(lead.website) if lead.website else ""

    # Derive state
    from crm.models import Deal
    deal = Deal.objects.filter(lead=lead).first()
    if deal and deal.stage:
        state = deal.stage.name.lower()
    elif getattr(lead, "disqualified", False):
        state = "disqualified"
    elif lead.description:
        state = "enriched"
    else:
        state = "url_only"

    positions = []
    if lead.description:
        try:
            profile = json.loads(lead.description)
            positions = profile.get("positions", [])
        except (json.JSONDecodeError, TypeError):
            pass

    return {
        "public_id": public_id,
        "url": lead.website or "",
        "state": state,
        "first_name": lead.first_name or "",
        "last_name": lead.last_name or "",
        "title": lead.title or "",
        "company": positions[0].get("company_name", "") if positions else "",
    }


class ProfileListView(APIView):
    authentication_classes = [ApiKeyAuthentication]
    permission_classes = [HasApiKey]

    def get(self, request):
        """List profiles, optionally filtered by state."""
        from crm.models import Lead
        qs = Lead.objects.select_related("company").prefetch_related()

        state_filter = request.query_params.get("state")
        if state_filter == "disqualified":
            qs = qs.filter(disqualified=True)
        elif state_filter == "enriched":
            qs = qs.filter(disqualified=False, contact__isnull=True).exclude(description="").exclude(description__isnull=True)
        elif state_filter == "url_only":
            qs = qs.filter(disqualified=False, contact__isnull=True).filter(description__isnull=True)
        elif state_filter in ("new", "pending", "connected", "completed", "failed"):
            from crm.models import Deal
            stage_name = state_filter.capitalize()
            deal_lead_ids = Deal.objects.filter(stage__name=stage_name).values_list("lead_id", flat=True)
            qs = qs.filter(pk__in=deal_lead_ids)

        campaign_id = request.query_params.get("campaign_id")
        if campaign_id:
            qs = qs.filter(department__campaign__id=campaign_id)

        data = [_lead_to_dict(lead) for lead in qs[:200]]
        return Response(data)

    def post(self, request):
        """Inject profile URLs into the pipeline (creates url_only Leads)."""
        ser = ProfileInjectSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        from linkedin.models import Campaign
        try:
            campaign = Campaign.objects.get(pk=ser.validated_data["campaign_id"])
        except Campaign.DoesNotExist:
            return Response({"error": "Campaign not found"}, status=404)

        # Build a minimal session-like object the DB functions expect
        from django.contrib.auth.models import AnonymousUser
        class _MinimalSession:
            django_user = campaign.department.manager_set.first() or __import__("django.contrib.auth.models", fromlist=["User"]).User.objects.first()
            def __init__(self, c):
                self.campaign = c

        session = _MinimalSession(campaign)

        results = []
        for url in ser.validated_data["urls"]:
            public_id = url_to_public_id(url)
            if not public_id:
                results.append({"url": url, "status": "invalid_url"})
                continue
            if lead_exists(url):
                results.append({"url": url, "status": "already_exists", "public_id": public_id})
                continue
            from crm.models import Lead
            clean_url = public_id_to_url(public_id)
            from linkedin.db.crm_profiles import _get_lead_source
            lead = Lead.objects.create(
                website=clean_url,
                owner=session.django_user,
                department=campaign.department,
                lead_source=_get_lead_source(session),
            )
            results.append({"url": url, "status": "created", "public_id": public_id, "lead_id": lead.pk})

        return Response(results, status=status.HTTP_207_MULTI_STATUS)


class ProfileDetailView(APIView):
    authentication_classes = [ApiKeyAuthentication]
    permission_classes = [HasApiKey]

    def get(self, request, public_id):
        from crm.models import Lead
        from linkedin.db.crm_profiles import public_id_to_url
        clean_url = public_id_to_url(public_id)
        lead = Lead.objects.filter(website=clean_url).first()
        if not lead:
            return Response({"error": "Profile not found"}, status=404)
        return Response(_lead_to_dict(lead))
```

**Step 3: Write tests**

Create `tests/test_api_profiles.py`:

```python
import pytest
from rest_framework.test import APIClient

from linkedin.models import ApiKey


@pytest.fixture
def api_client():
    _, raw = ApiKey.generate("test")
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Api-Key {raw}")
    return client


@pytest.mark.django_db
def test_profiles_list_requires_auth():
    client = APIClient()
    resp = client.get("/api/v1/profiles/")
    assert resp.status_code == 403


@pytest.mark.django_db
def test_profiles_list_empty(api_client):
    resp = api_client.get("/api/v1/profiles/")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.django_db
def test_profile_inject_invalid_url(api_client):
    from common.models import Department
    from linkedin.models import Campaign
    dept = Department.objects.create(name="T")
    campaign = Campaign.objects.create(department=dept)
    resp = api_client.post("/api/v1/profiles/", {
        "urls": ["not-a-url"],
        "campaign_id": campaign.pk,
    }, format="json")
    assert resp.status_code == 400
```

**Step 4: Run tests**

```bash
pytest tests/test_api_profiles.py -v
```

Expected: PASS (the inject test should 400 on invalid URL format).

**Step 5: Commit**

```bash
git add linkedin/rest_api/views/ tests/test_api_profiles.py
git commit -m "feat: add profile list/detail/inject API views"
```

---

### Task 6: Campaign Views

**Files:**
- Create: `linkedin/rest_api/views/campaigns.py`

**Step 1: Create `linkedin/rest_api/views/campaigns.py`**

```python
from rest_framework.views import APIView
from rest_framework.response import Response

from linkedin.models import Campaign
from linkedin.rest_api.authentication import ApiKeyAuthentication
from linkedin.rest_api.permissions import HasApiKey
from linkedin.rest_api.serializers import CampaignSerializer


class CampaignListView(APIView):
    authentication_classes = [ApiKeyAuthentication]
    permission_classes = [HasApiKey]

    def get(self, request):
        campaigns = Campaign.objects.select_related("department").all()
        return Response(CampaignSerializer(campaigns, many=True).data)


class CampaignDetailView(APIView):
    authentication_classes = [ApiKeyAuthentication]
    permission_classes = [HasApiKey]

    def _get(self, pk):
        try:
            return Campaign.objects.select_related("department").get(pk=pk)
        except Campaign.DoesNotExist:
            return None

    def get(self, request, pk):
        campaign = self._get(pk)
        if not campaign:
            return Response({"error": "Not found"}, status=404)
        return Response(CampaignSerializer(campaign).data)

    def patch(self, request, pk):
        campaign = self._get(pk)
        if not campaign:
            return Response({"error": "Not found"}, status=404)
        ser = CampaignSerializer(campaign, data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        ser.save()
        return Response(CampaignSerializer(campaign).data)
```

**Step 2: Write tests**

Append to `tests/test_api_campaigns.py`:

```python
import pytest
from rest_framework.test import APIClient
from linkedin.models import ApiKey, Campaign
from common.models import Department


@pytest.fixture
def api_client():
    _, raw = ApiKey.generate("test")
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Api-Key {raw}")
    return client


@pytest.fixture
def campaign(db):
    dept = Department.objects.create(name="Acme")
    return Campaign.objects.create(department=dept, product_docs="old docs")


@pytest.mark.django_db
def test_campaign_list(api_client, campaign):
    resp = api_client.get("/api/v1/campaigns/")
    assert resp.status_code == 200
    assert any(c["id"] == campaign.pk for c in resp.json())


@pytest.mark.django_db
def test_campaign_patch(api_client, campaign):
    resp = api_client.patch(f"/api/v1/campaigns/{campaign.pk}/", {"product_docs": "new docs"}, format="json")
    assert resp.status_code == 200
    campaign.refresh_from_db()
    assert campaign.product_docs == "new docs"
```

**Step 3: Run tests**

```bash
pytest tests/test_api_campaigns.py -v
```

**Step 4: Commit**

```bash
git add linkedin/rest_api/views/campaigns.py tests/test_api_campaigns.py
git commit -m "feat: add campaign list/detail/patch API views"
```

---

### Task 7: Lane Trigger + Job Views

**Files:**
- Create: `linkedin/rest_api/views/jobs.py`

**Step 1: Create `linkedin/rest_api/views/jobs.py`**

```python
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from linkedin.models import ActionJob, Campaign
from linkedin.rest_api.authentication import ApiKeyAuthentication
from linkedin.rest_api.permissions import HasApiKey
from linkedin.rest_api.serializers import ActionJobSerializer, LaneTriggerSerializer


class LaneTriggerView(APIView):
    authentication_classes = [ApiKeyAuthentication]
    permission_classes = [HasApiKey]

    def post(self, request, lane):
        data = dict(request.data)
        data["lane"] = lane
        ser = LaneTriggerSerializer(data=data)
        ser.is_valid(raise_exception=True)

        try:
            campaign = Campaign.objects.get(pk=ser.validated_data["campaign_id"])
        except Campaign.DoesNotExist:
            return Response({"error": "Campaign not found"}, status=404)

        job = ActionJob.objects.create(
            lane=lane,
            params=ser.validated_data.get("params", {}),
            campaign=campaign,
        )
        return Response(ActionJobSerializer(job).data, status=status.HTTP_202_ACCEPTED)


class JobListView(APIView):
    authentication_classes = [ApiKeyAuthentication]
    permission_classes = [HasApiKey]

    def get(self, request):
        qs = ActionJob.objects.order_by("-created_at")[:50]
        status_filter = request.query_params.get("status")
        if status_filter:
            qs = ActionJob.objects.filter(status=status_filter).order_by("-created_at")[:50]
        return Response(ActionJobSerializer(qs, many=True).data)


class JobDetailView(APIView):
    authentication_classes = [ApiKeyAuthentication]
    permission_classes = [HasApiKey]

    def get(self, request, pk):
        try:
            job = ActionJob.objects.get(pk=pk)
        except ActionJob.DoesNotExist:
            return Response({"error": "Not found"}, status=404)
        return Response(ActionJobSerializer(job).data)
```

**Step 2: Write tests**

Create `tests/test_api_jobs.py`:

```python
import pytest
from rest_framework.test import APIClient
from linkedin.models import ApiKey, Campaign, ActionJob
from common.models import Department


@pytest.fixture
def api_client():
    _, raw = ApiKey.generate("test")
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Api-Key {raw}")
    return client


@pytest.fixture
def campaign(db):
    dept = Department.objects.create(name="Sales")
    return Campaign.objects.create(department=dept)


@pytest.mark.django_db
def test_trigger_search_lane(api_client, campaign):
    resp = api_client.post("/api/v1/lanes/search/trigger/", {
        "campaign_id": campaign.pk,
        "params": {"keyword": "Head of Growth"},
    }, format="json")
    assert resp.status_code == 202
    data = resp.json()
    assert data["lane"] == "search"
    assert data["status"] == "pending"
    assert ActionJob.objects.filter(pk=data["id"]).exists()


@pytest.mark.django_db
def test_trigger_invalid_lane(api_client, campaign):
    resp = api_client.post("/api/v1/lanes/teleport/trigger/", {
        "campaign_id": campaign.pk,
    }, format="json")
    assert resp.status_code == 400


@pytest.mark.django_db
def test_job_poll(api_client, campaign):
    job = ActionJob.objects.create(lane="connect", campaign=campaign, status="completed", result={"ok": True})
    resp = api_client.get(f"/api/v1/jobs/{job.pk}/")
    assert resp.status_code == 200
    assert resp.json()["status"] == "completed"
```

**Step 3: Run tests**

```bash
pytest tests/test_api_jobs.py -v
```

Expected: 3 PASS.

**Step 4: Commit**

```bash
git add linkedin/rest_api/views/jobs.py tests/test_api_jobs.py
git commit -m "feat: add lane trigger and job polling API views"
```

---

### Task 8: Webhook Views + Dispatch Helper

**Files:**
- Create: `linkedin/rest_api/views/webhooks.py`
- Create: `linkedin/rest_api/webhooks.py`

**Step 1: Create `linkedin/rest_api/views/webhooks.py`**

```python
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from linkedin.models import WebhookSubscription
from linkedin.rest_api.authentication import ApiKeyAuthentication
from linkedin.rest_api.permissions import HasApiKey
from linkedin.rest_api.serializers import WebhookSerializer


class WebhookListView(APIView):
    authentication_classes = [ApiKeyAuthentication]
    permission_classes = [HasApiKey]

    def get(self, request):
        qs = WebhookSubscription.objects.filter(active=True)
        return Response(WebhookSerializer(qs, many=True).data)

    def post(self, request):
        ser = WebhookSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        ser.save()
        return Response(ser.data, status=status.HTTP_201_CREATED)


class WebhookDetailView(APIView):
    authentication_classes = [ApiKeyAuthentication]
    permission_classes = [HasApiKey]

    def delete(self, request, pk):
        try:
            hook = WebhookSubscription.objects.get(pk=pk)
        except WebhookSubscription.DoesNotExist:
            return Response(status=404)
        hook.active = False
        hook.save()
        return Response(status=204)
```

**Step 2: Create `linkedin/rest_api/webhooks.py`**

```python
"""Webhook delivery: POST event payloads to registered subscribers."""
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def dispatch_webhooks(event: str, job) -> None:
    """Fire-and-forget: POST event to all active, matching webhook subscribers."""
    try:
        import httpx
        from linkedin.models import WebhookSubscription

        subscribers = WebhookSubscription.objects.filter(active=True)
        if job.campaign_id:
            subscribers = subscribers.filter(
                campaign__isnull=True
            ) | subscribers.filter(campaign_id=job.campaign_id)

        payload = {
            "event": event,
            "job_id": str(job.pk),
            "lane": job.lane,
            "campaign_id": job.campaign_id,
            "result": job.result,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        for sub in subscribers:
            if event not in sub.events:
                continue
            try:
                httpx.post(sub.url, json=payload, timeout=10)
                logger.debug("Webhook delivered: %s → %s", event, sub.url)
            except Exception as e:
                logger.warning("Webhook delivery failed for %s: %s", sub.url, e)
    except Exception as e:
        logger.warning("dispatch_webhooks error: %s", e)
```

**Step 3: Commit**

```bash
git add linkedin/rest_api/views/webhooks.py linkedin/rest_api/webhooks.py
git commit -m "feat: add webhook subscription views and dispatch helper"
```

---

### Task 9: URL Configuration

**Files:**
- Create: `linkedin/rest_api/urls.py`
- Modify: `linkedin/urls.py`

**Step 1: Create `linkedin/rest_api/urls.py`**

```python
from django.urls import path

from linkedin.rest_api.views.profiles import ProfileListView, ProfileDetailView
from linkedin.rest_api.views.campaigns import CampaignListView, CampaignDetailView
from linkedin.rest_api.views.jobs import LaneTriggerView, JobListView, JobDetailView
from linkedin.rest_api.views.webhooks import WebhookListView, WebhookDetailView

urlpatterns = [
    # Profiles
    path("profiles/", ProfileListView.as_view(), name="api-profiles"),
    path("profiles/<str:public_id>/", ProfileDetailView.as_view(), name="api-profile-detail"),

    # Campaigns
    path("campaigns/", CampaignListView.as_view(), name="api-campaigns"),
    path("campaigns/<int:pk>/", CampaignDetailView.as_view(), name="api-campaign-detail"),

    # Lane triggers
    path("lanes/<str:lane>/trigger/", LaneTriggerView.as_view(), name="api-lane-trigger"),

    # Jobs
    path("jobs/", JobListView.as_view(), name="api-jobs"),
    path("jobs/<int:pk>/", JobDetailView.as_view(), name="api-job-detail"),

    # Webhooks
    path("webhooks/", WebhookListView.as_view(), name="api-webhooks"),
    path("webhooks/<int:pk>/", WebhookDetailView.as_view(), name="api-webhook-detail"),
]
```

**Step 2: Wire into `linkedin/urls.py`**

Add to the existing `urlpatterns`:

```python
from django.urls import include, path
# ... existing imports ...

urlpatterns = [
    path("crm/", include("crm.urls")),
    path("crm/", include("common.urls")),
    path("admin/", admin.site.urls),
    path("api/v1/", include("linkedin.rest_api.urls")),  # ← add this
]
```

**Step 3: Run full test suite**

```bash
pytest tests/ -v
```

Expected: all existing + new tests pass.

**Step 4: Commit**

```bash
git add linkedin/rest_api/urls.py linkedin/urls.py
git commit -m "feat: wire /api/v1/ URL routes"
```

---

### Task 10: Admin Registration for New Models

**Files:**
- Modify: `linkedin/admin.py`

**Step 1: Add to `linkedin/admin.py`**

```python
from linkedin.models import ApiKey, ActionJob, WebhookSubscription

@admin.register(ApiKey)
class ApiKeyAdmin(admin.ModelAdmin):
    list_display = ("name", "active", "created_at")
    readonly_fields = ("key_hash", "created_at")

@admin.register(ActionJob)
class ActionJobAdmin(admin.ModelAdmin):
    list_display = ("lane", "status", "campaign", "created_at", "updated_at")
    list_filter = ("status", "lane")
    readonly_fields = ("result", "created_at", "updated_at")

@admin.register(WebhookSubscription)
class WebhookSubscriptionAdmin(admin.ModelAdmin):
    list_display = ("url", "events", "active", "created_at")
```

**Step 2: Commit**

```bash
git add linkedin/admin.py
git commit -m "feat: register ApiKey, ActionJob, WebhookSubscription in Django Admin"
```

---

### Task 11: Daemon Integration — Process ActionJobs

**Files:**
- Modify: `linkedin/daemon.py`

**Step 1: Add `_process_action_jobs()` to `linkedin/daemon.py`**

Add this function after the `_rebuild_analytics` function (around line 78):

```python
def _process_action_jobs(session):
    """Execute one pending ActionJob per daemon tick.

    Called after each major lane tick. Picks the oldest pending job,
    executes the appropriate lane, and marks it completed/failed.
    Dispatches webhooks on completion.
    """
    from linkedin.models import ActionJob, Campaign
    from linkedin.rest_api.webhooks import dispatch_webhooks

    job = ActionJob.objects.filter(status="pending").order_by("created_at").first()
    if not job:
        return

    job.status = "running"
    job.save(update_fields=["status", "updated_at"])

    # Set campaign context
    if job.campaign:
        session.campaign = job.campaign
    elif not session.campaign:
        job.status = "failed"
        job.result = {"error": "No campaign set and job has no campaign"}
        job.save(update_fields=["status", "result", "updated_at"])
        dispatch_webhooks("job.failed", job)
        return

    logger.info("Processing ActionJob #%d: %s", job.pk, job.lane)

    try:
        result = _execute_action_job(session, job)
        job.status = "completed"
        job.result = result or {}
    except Exception as exc:
        logger.exception("ActionJob #%d failed: %s", job.pk, exc)
        job.status = "failed"
        job.result = {"error": str(exc)}
    finally:
        job.save(update_fields=["status", "result", "updated_at"])
        dispatch_webhooks("job." + job.status, job)


def _execute_action_job(session, job) -> dict:
    """Map job.lane to the appropriate lane execute() call. Returns result dict."""
    from linkedin.conf import CAMPAIGN_CONFIG, MODEL_PATH
    from linkedin.ml.qualifier import BayesianQualifier
    from linkedin.ml.embeddings import get_labeled_data
    from linkedin.rate_limiter import RateLimiter

    cfg = CAMPAIGN_CONFIG
    lp = session.linkedin_profile

    if job.lane == "search":
        from linkedin.actions.search import search_people
        keyword = job.params.get("keyword", "")
        if not keyword:
            raise ValueError("search lane requires params.keyword")
        search_people(session, keyword)
        return {"keyword": keyword}

    elif job.lane == "connect":
        from linkedin.lanes.connect import ConnectLane
        qualifier = BayesianQualifier(seed=42, n_mc_samples=cfg["qualification_n_mc_samples"], save_path=MODEL_PATH)
        X, y = get_labeled_data()
        if len(X) > 0:
            qualifier.warm_start(X, y)
        limiter = RateLimiter(daily_limit=lp.connect_daily_limit, weekly_limit=lp.connect_weekly_limit)
        lane = ConnectLane(session, limiter, qualifier)
        if lane.can_execute():
            lane.execute()
            return {"executed": True}
        return {"executed": False, "reason": "nothing to connect"}

    elif job.lane == "follow_up":
        from linkedin.lanes.follow_up import FollowUpLane
        limiter = RateLimiter(daily_limit=lp.follow_up_daily_limit)
        lane = FollowUpLane(session, limiter)
        if lane.can_execute():
            lane.execute()
            return {"executed": True}
        return {"executed": False, "reason": "nothing to follow up"}

    elif job.lane == "check_pending":
        from linkedin.lanes.check_pending import CheckPendingLane
        lane = CheckPendingLane(session, cfg["check_pending_recheck_after_hours"])
        if lane.can_execute():
            lane.execute()
            return {"executed": True}
        return {"executed": False}

    elif job.lane == "qualify":
        from linkedin.lanes.qualify import QualifyLane
        qualifier = BayesianQualifier(seed=42, n_mc_samples=cfg["qualification_n_mc_samples"], save_path=MODEL_PATH)
        X, y = get_labeled_data()
        if len(X) > 0:
            qualifier.warm_start(X, y)
        lane = QualifyLane(session, qualifier)
        if lane.can_execute():
            lane.execute()
            return {"executed": True}
        return {"executed": False}

    raise ValueError(f"Unknown lane: {job.lane}")
```

**Step 2: Call `_process_action_jobs` in the daemon loop**

In `run_daemon()`, find the section after `next_schedule.lane.execute()` (around line 239) and add the call:

```python
        if next_schedule.lane.can_execute():
            next_schedule.lane.execute()
            next_schedule.reschedule()
            promo.tick()
        else:
            next_schedule.next_run = time.time() + 60

        # ── Process any queued API jobs ──
        _process_action_jobs(session)   # ← add this line
```

**Step 3: Commit**

```bash
git add linkedin/daemon.py
git commit -m "feat: add _process_action_jobs to daemon loop for API-triggered actions"
```

---

### Task 12: DRF Global Settings

**Files:**
- Modify: `linkedin/django_settings.py`

**Step 1: Add DRF default settings**

Append to `linkedin/django_settings.py`:

```python
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "linkedin.rest_api.authentication.ApiKeyAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "linkedin.rest_api.permissions.HasApiKey",
    ],
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
}
```

**Step 2: Run full test suite**

```bash
pytest tests/ -v
```

Expected: all tests pass.

**Step 3: Commit**

```bash
git add linkedin/django_settings.py
git commit -m "feat: add DRF global settings (auth, permissions, renderer)"
```

---

## Phase 2: n8n Community Node

> The n8n node lives in a **separate repository/directory** from OpenOutreach. Create it alongside (not inside) the OpenOutreach repo.

---

### Task 13: Initialize n8n Node Package

**Directory:** `n8n-nodes-openoutreach/` (sibling to `OpenOutreach/`)

**Step 1: Initialize package**

```bash
mkdir n8n-nodes-openoutreach && cd n8n-nodes-openoutreach
npm init -y
```

**Step 2: Set `package.json`**

Replace `package.json` with:

```json
{
  "name": "n8n-nodes-openoutreach",
  "version": "0.1.0",
  "description": "n8n community node for OpenOutreach LinkedIn automation",
  "keywords": ["n8n-community-node-package"],
  "license": "GPL-3.0",
  "homepage": "https://github.com/eracle/OpenOutreach",
  "main": "index.js",
  "scripts": {
    "build": "tsc && npm run copy-icons",
    "copy-icons": "cp nodes/OpenOutreach/openoutreach.svg dist/nodes/OpenOutreach/",
    "dev": "tsc --watch"
  },
  "n8n": {
    "n8nNodesApiVersion": 1,
    "credentials": ["dist/credentials/OpenOutreachApi.credentials.js"],
    "nodes": ["dist/nodes/OpenOutreach/OpenOutreach.node.js"]
  },
  "devDependencies": {
    "typescript": "^5.3.0",
    "n8n-workflow": "*"
  }
}
```

**Step 3: Create `tsconfig.json`**

```json
{
  "compilerOptions": {
    "target": "ES2019",
    "module": "commonjs",
    "lib": ["ES2019"],
    "outDir": "dist",
    "rootDir": ".",
    "strict": true,
    "esModuleInterop": true,
    "resolveJsonModule": true,
    "declaration": true,
    "declarationMap": true,
    "sourceMap": true
  },
  "include": ["credentials/**/*", "nodes/**/*", "index.ts"],
  "exclude": ["node_modules", "dist"]
}
```

**Step 4: Install deps**

```bash
npm install
```

**Step 5: Commit**

```bash
git init && git add . && git commit -m "feat: initialize n8n-nodes-openoutreach package"
```

---

### Task 14: Credentials

**Files:**
- Create: `credentials/OpenOutreachApi.credentials.ts`

**Step 1: Create credentials file**

```typescript
import {
  ICredentialType,
  INodeProperties,
} from 'n8n-workflow';

export class OpenOutreachApi implements ICredentialType {
  name = 'openOutreachApi';
  displayName = 'OpenOutreach API';
  documentationUrl = 'https://github.com/eracle/OpenOutreach';
  properties: INodeProperties[] = [
    {
      displayName: 'Base URL',
      name: 'baseUrl',
      type: 'string',
      default: 'https://openoutreach.example.com',
      placeholder: 'https://your-openoutreach-host.com',
      description: 'The URL where your OpenOutreach instance is running',
    },
    {
      displayName: 'API Key',
      name: 'apiKey',
      type: 'string',
      typeOptions: { password: true },
      default: '',
      description: 'API key from OpenOutreach Django Admin → API Keys',
    },
  ];
}
```

**Step 2: Build to verify**

```bash
npm run build
```

Expected: `dist/credentials/OpenOutreachApi.credentials.js` created.

**Step 3: Commit**

```bash
git add credentials/ && git commit -m "feat: add OpenOutreachApi credentials"
```

---

### Task 15: Helper — API request utility

**Files:**
- Create: `nodes/OpenOutreach/helpers.ts`

**Step 1: Create `nodes/OpenOutreach/helpers.ts`**

```typescript
import { IExecuteFunctions, ILoadOptionsFunctions } from 'n8n-workflow';

export async function openOutreachRequest(
  this: IExecuteFunctions | ILoadOptionsFunctions,
  method: 'GET' | 'POST' | 'PATCH' | 'DELETE',
  path: string,
  body?: object,
  qs?: object,
): Promise<any> {
  const credentials = await this.getCredentials('openOutreachApi');
  const baseUrl = (credentials.baseUrl as string).replace(/\/$/, '');
  const apiKey = credentials.apiKey as string;

  const options = {
    method,
    url: `${baseUrl}/api/v1${path}`,
    headers: {
      Authorization: `Api-Key ${apiKey}`,
      'Content-Type': 'application/json',
    },
    body,
    qs,
    json: true,
  };

  return this.helpers.request(options);
}

export async function pollJobUntilDone(
  ctx: IExecuteFunctions,
  jobId: string,
  timeoutMs = 300_000,
  intervalMs = 5_000,
): Promise<any> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const job = await openOutreachRequest.call(ctx, 'GET', `/jobs/${jobId}/`);
    if (job.status === 'completed' || job.status === 'failed') {
      return job;
    }
    await new Promise(resolve => setTimeout(resolve, intervalMs));
  }
  throw new Error(`Job ${jobId} timed out after ${timeoutMs / 1000}s`);
}
```

**Step 2: Commit**

```bash
git add nodes/OpenOutreach/helpers.ts && git commit -m "feat: add API request helper and job polling utility"
```

---

### Task 16: Profiles Resource Operations

**Files:**
- Create: `nodes/OpenOutreach/actions/profiles.ts`

**Step 1: Create `nodes/OpenOutreach/actions/profiles.ts`**

```typescript
import { IExecuteFunctions, INodeExecutionData, INodeProperties } from 'n8n-workflow';
import { openOutreachRequest } from '../helpers';

export const profilesOperations: INodeProperties[] = [
  {
    displayName: 'Operation',
    name: 'operation',
    type: 'options',
    noDataExpression: true,
    displayOptions: { show: { resource: ['profiles'] } },
    options: [
      { name: 'Get Many', value: 'getMany', description: 'List profiles filtered by state' },
      { name: 'Get', value: 'get', description: 'Get a single profile by public ID' },
      { name: 'Inject', value: 'inject', description: 'Add LinkedIn profile URLs to the pipeline' },
    ],
    default: 'getMany',
  },
];

export const profilesFields: INodeProperties[] = [
  // getMany
  {
    displayName: 'State Filter',
    name: 'state',
    type: 'options',
    displayOptions: { show: { resource: ['profiles'], operation: ['getMany'] } },
    options: [
      { name: 'All', value: '' },
      { name: 'URL Only (Discovered)', value: 'url_only' },
      { name: 'Enriched', value: 'enriched' },
      { name: 'Qualified (New)', value: 'new' },
      { name: 'Pending', value: 'pending' },
      { name: 'Connected', value: 'connected' },
      { name: 'Completed', value: 'completed' },
      { name: 'Disqualified', value: 'disqualified' },
    ],
    default: '',
  },
  // get
  {
    displayName: 'Public ID',
    name: 'publicId',
    type: 'string',
    required: true,
    displayOptions: { show: { resource: ['profiles'], operation: ['get'] } },
    default: '',
    description: 'LinkedIn public identifier (e.g. john-doe-123)',
  },
  // inject
  {
    displayName: 'Profile URLs',
    name: 'urls',
    type: 'string',
    typeOptions: { multipleValues: true },
    required: true,
    displayOptions: { show: { resource: ['profiles'], operation: ['inject'] } },
    default: [],
    description: 'LinkedIn profile URLs to add to the pipeline',
  },
  {
    displayName: 'Campaign ID',
    name: 'campaignId',
    type: 'number',
    required: true,
    displayOptions: { show: { resource: ['profiles'], operation: ['inject'] } },
    default: 1,
  },
];

export async function executeProfiles(
  this: IExecuteFunctions,
  i: number,
): Promise<INodeExecutionData[]> {
  const operation = this.getNodeParameter('operation', i) as string;

  if (operation === 'getMany') {
    const state = this.getNodeParameter('state', i) as string;
    const qs = state ? { state } : {};
    const results = await openOutreachRequest.call(this, 'GET', '/profiles/', undefined, qs);
    return (results as any[]).map(r => ({ json: r }));
  }

  if (operation === 'get') {
    const publicId = this.getNodeParameter('publicId', i) as string;
    const result = await openOutreachRequest.call(this, 'GET', `/profiles/${publicId}/`);
    return [{ json: result }];
  }

  if (operation === 'inject') {
    const urls = this.getNodeParameter('urls', i) as string[];
    const campaignId = this.getNodeParameter('campaignId', i) as number;
    const results = await openOutreachRequest.call(this, 'POST', '/profiles/', {
      urls,
      campaign_id: campaignId,
    });
    return (results as any[]).map(r => ({ json: r }));
  }

  throw new Error(`Unknown profiles operation: ${operation}`);
}
```

**Step 2: Build and verify**

```bash
npm run build
```

Expected: no TypeScript errors.

**Step 3: Commit**

```bash
git add nodes/OpenOutreach/actions/profiles.ts && git commit -m "feat: add Profiles resource (getMany/get/inject)"
```

---

### Task 17: Campaigns + Lanes + Jobs + Webhooks Resources

**Files:**
- Create: `nodes/OpenOutreach/actions/campaigns.ts`
- Create: `nodes/OpenOutreach/actions/lanes.ts`
- Create: `nodes/OpenOutreach/actions/jobs.ts`

**Step 1: Create `nodes/OpenOutreach/actions/campaigns.ts`**

```typescript
import { IExecuteFunctions, INodeExecutionData, INodeProperties } from 'n8n-workflow';
import { openOutreachRequest } from '../helpers';

export const campaignsOperations: INodeProperties[] = [
  {
    displayName: 'Operation',
    name: 'operation',
    type: 'options',
    noDataExpression: true,
    displayOptions: { show: { resource: ['campaigns'] } },
    options: [
      { name: 'Get Many', value: 'getMany' },
      { name: 'Get', value: 'get' },
      { name: 'Update', value: 'update' },
    ],
    default: 'getMany',
  },
];

export const campaignsFields: INodeProperties[] = [
  { displayName: 'Campaign ID', name: 'campaignId', type: 'number', required: true,
    displayOptions: { show: { resource: ['campaigns'], operation: ['get', 'update'] } }, default: 1 },
  { displayName: 'Product Docs', name: 'productDocs', type: 'string', typeOptions: { rows: 4 },
    displayOptions: { show: { resource: ['campaigns'], operation: ['update'] } }, default: '' },
  { displayName: 'Campaign Objective', name: 'campaignObjective', type: 'string', typeOptions: { rows: 4 },
    displayOptions: { show: { resource: ['campaigns'], operation: ['update'] } }, default: '' },
  { displayName: 'Follow-up Template', name: 'followupTemplate', type: 'string', typeOptions: { rows: 6 },
    displayOptions: { show: { resource: ['campaigns'], operation: ['update'] } }, default: '' },
  { displayName: 'Booking Link', name: 'bookingLink', type: 'string',
    displayOptions: { show: { resource: ['campaigns'], operation: ['update'] } }, default: '' },
];

export async function executeCampaigns(this: IExecuteFunctions, i: number): Promise<INodeExecutionData[]> {
  const operation = this.getNodeParameter('operation', i) as string;
  if (operation === 'getMany') {
    const r = await openOutreachRequest.call(this, 'GET', '/campaigns/');
    return (r as any[]).map(x => ({ json: x }));
  }
  const campaignId = this.getNodeParameter('campaignId', i) as number;
  if (operation === 'get') {
    return [{ json: await openOutreachRequest.call(this, 'GET', `/campaigns/${campaignId}/`) }];
  }
  if (operation === 'update') {
    const body: any = {};
    const pd = this.getNodeParameter('productDocs', i, '') as string;
    const co = this.getNodeParameter('campaignObjective', i, '') as string;
    const ft = this.getNodeParameter('followupTemplate', i, '') as string;
    const bl = this.getNodeParameter('bookingLink', i, '') as string;
    if (pd) body.product_docs = pd;
    if (co) body.campaign_objective = co;
    if (ft) body.followup_template = ft;
    if (bl) body.booking_link = bl;
    return [{ json: await openOutreachRequest.call(this, 'PATCH', `/campaigns/${campaignId}/`, body) }];
  }
  throw new Error(`Unknown campaigns operation: ${operation}`);
}
```

**Step 2: Create `nodes/OpenOutreach/actions/lanes.ts`**

```typescript
import { IExecuteFunctions, INodeExecutionData, INodeProperties } from 'n8n-workflow';
import { openOutreachRequest, pollJobUntilDone } from '../helpers';

export const lanesOperations: INodeProperties[] = [
  {
    displayName: 'Operation',
    name: 'operation',
    type: 'options',
    noDataExpression: true,
    displayOptions: { show: { resource: ['lanes'] } },
    options: [{ name: 'Trigger', value: 'trigger', description: 'Queue a lane action for the daemon to execute' }],
    default: 'trigger',
  },
];

export const lanesFields: INodeProperties[] = [
  {
    displayName: 'Lane',
    name: 'lane',
    type: 'options',
    required: true,
    displayOptions: { show: { resource: ['lanes'], operation: ['trigger'] } },
    options: [
      { name: 'Connect', value: 'connect' },
      { name: 'Check Pending', value: 'check_pending' },
      { name: 'Follow Up', value: 'follow_up' },
      { name: 'Qualify', value: 'qualify' },
      { name: 'Search', value: 'search' },
    ],
    default: 'search',
  },
  { displayName: 'Campaign ID', name: 'campaignId', type: 'number', required: true,
    displayOptions: { show: { resource: ['lanes'], operation: ['trigger'] } }, default: 1 },
  { displayName: 'Keyword (Search lane only)', name: 'keyword', type: 'string',
    displayOptions: { show: { resource: ['lanes'], operation: ['trigger'], lane: ['search'] } }, default: '' },
  {
    displayName: 'Wait for Completion',
    name: 'waitForCompletion',
    type: 'boolean',
    displayOptions: { show: { resource: ['lanes'], operation: ['trigger'] } },
    default: false,
    description: 'Poll until the job finishes. Can take 30-120s (browser automation).',
  },
  { displayName: 'Timeout (seconds)', name: 'timeoutSeconds', type: 'number',
    displayOptions: { show: { resource: ['lanes'], operation: ['trigger'], waitForCompletion: [true] } }, default: 300 },
];

export async function executeLanes(this: IExecuteFunctions, i: number): Promise<INodeExecutionData[]> {
  const lane = this.getNodeParameter('lane', i) as string;
  const campaignId = this.getNodeParameter('campaignId', i) as number;
  const waitForCompletion = this.getNodeParameter('waitForCompletion', i) as boolean;

  const params: any = {};
  if (lane === 'search') {
    params.keyword = this.getNodeParameter('keyword', i) as string;
  }

  const job = await openOutreachRequest.call(this, 'POST', `/lanes/${lane}/trigger/`, {
    campaign_id: campaignId,
    params,
  });

  if (waitForCompletion) {
    const timeoutSeconds = this.getNodeParameter('timeoutSeconds', i, 300) as number;
    const result = await pollJobUntilDone(this, String(job.id), timeoutSeconds * 1000);
    return [{ json: result }];
  }

  return [{ json: job }];
}
```

**Step 3: Create `nodes/OpenOutreach/actions/jobs.ts`**

```typescript
import { IExecuteFunctions, INodeExecutionData, INodeProperties } from 'n8n-workflow';
import { openOutreachRequest } from '../helpers';

export const jobsOperations: INodeProperties[] = [
  {
    displayName: 'Operation',
    name: 'operation',
    type: 'options',
    noDataExpression: true,
    displayOptions: { show: { resource: ['jobs'] } },
    options: [
      { name: 'Get', value: 'get' },
      { name: 'Get Many', value: 'getMany' },
    ],
    default: 'get',
  },
];

export const jobsFields: INodeProperties[] = [
  { displayName: 'Job ID', name: 'jobId', type: 'string', required: true,
    displayOptions: { show: { resource: ['jobs'], operation: ['get'] } }, default: '' },
  { displayName: 'Status Filter', name: 'status', type: 'options',
    displayOptions: { show: { resource: ['jobs'], operation: ['getMany'] } },
    options: [
      { name: 'All', value: '' }, { name: 'Pending', value: 'pending' },
      { name: 'Running', value: 'running' }, { name: 'Completed', value: 'completed' },
      { name: 'Failed', value: 'failed' },
    ],
    default: '' },
];

export async function executeJobs(this: IExecuteFunctions, i: number): Promise<INodeExecutionData[]> {
  const operation = this.getNodeParameter('operation', i) as string;
  if (operation === 'get') {
    const jobId = this.getNodeParameter('jobId', i) as string;
    return [{ json: await openOutreachRequest.call(this, 'GET', `/jobs/${jobId}/`) }];
  }
  const status = this.getNodeParameter('status', i) as string;
  const qs = status ? { status } : {};
  const r = await openOutreachRequest.call(this, 'GET', '/jobs/', undefined, qs);
  return (r as any[]).map(x => ({ json: x }));
}
```

**Step 4: Build and verify**

```bash
npm run build
```

Expected: no errors.

**Step 5: Commit**

```bash
git add nodes/OpenOutreach/actions/ && git commit -m "feat: add Campaigns, Lanes (with polling), Jobs resources"
```

---

### Task 18: Main Node File

**Files:**
- Create: `nodes/OpenOutreach/OpenOutreach.node.ts`
- Create: `nodes/OpenOutreach/OpenOutreach.node.json`
- Create: `index.ts`

**Step 1: Create `nodes/OpenOutreach/OpenOutreach.node.ts`**

```typescript
import {
  IExecuteFunctions,
  INodeExecutionData,
  INodeType,
  INodeTypeDescription,
} from 'n8n-workflow';

import { profilesOperations, profilesFields, executeProfiles } from './actions/profiles';
import { campaignsOperations, campaignsFields, executeCampaigns } from './actions/campaigns';
import { lanesOperations, lanesFields, executeLanes } from './actions/lanes';
import { jobsOperations, jobsFields, executeJobs } from './actions/jobs';

export class OpenOutreach implements INodeType {
  description: INodeTypeDescription = {
    displayName: 'OpenOutreach',
    name: 'openOutreach',
    icon: 'file:openoutreach.svg',
    group: ['transform'],
    version: 1,
    subtitle: '={{$parameter["resource"] + ": " + $parameter["operation"]}}',
    description: 'Interact with OpenOutreach LinkedIn automation',
    defaults: { name: 'OpenOutreach' },
    inputs: ['main'],
    outputs: ['main'],
    credentials: [{ name: 'openOutreachApi', required: true }],
    properties: [
      {
        displayName: 'Resource',
        name: 'resource',
        type: 'options',
        noDataExpression: true,
        options: [
          { name: 'Profiles', value: 'profiles' },
          { name: 'Campaigns', value: 'campaigns' },
          { name: 'Lanes', value: 'lanes' },
          { name: 'Jobs', value: 'jobs' },
        ],
        default: 'profiles',
      },
      ...profilesOperations,
      ...profilesFields,
      ...campaignsOperations,
      ...campaignsFields,
      ...lanesOperations,
      ...lanesFields,
      ...jobsOperations,
      ...jobsFields,
    ],
  };

  async execute(this: IExecuteFunctions): Promise<INodeExecutionData[][]> {
    const items = this.getInputData();
    const resource = this.getNodeParameter('resource', 0) as string;
    let results: INodeExecutionData[] = [];

    for (let i = 0; i < items.length; i++) {
      if (resource === 'profiles') results.push(...await executeProfiles.call(this, i));
      else if (resource === 'campaigns') results.push(...await executeCampaigns.call(this, i));
      else if (resource === 'lanes') results.push(...await executeLanes.call(this, i));
      else if (resource === 'jobs') results.push(...await executeJobs.call(this, i));
      else throw new Error(`Unknown resource: ${resource}`);
    }

    return [results];
  }
}
```

**Step 2: Create `nodes/OpenOutreach/OpenOutreach.node.json`**

```json
{
  "node": "n8n-nodes-openoutreach.openOutreach",
  "nodeVersion": "1.0",
  "codexVersion": "1.0",
  "categories": ["Marketing"],
  "resources": {
    "primaryDocumentation": [
      { "url": "https://github.com/eracle/OpenOutreach" }
    ]
  }
}
```

**Step 3: Create `index.ts`**

```typescript
export { OpenOutreach } from './nodes/OpenOutreach/OpenOutreach.node';
export { OpenOutreachApi } from './credentials/OpenOutreachApi.credentials';
```

**Step 4: Add placeholder SVG**

Create `nodes/OpenOutreach/openoutreach.svg` with any simple SVG. Replace with the real logo later.

```xml
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
  <rect width="64" height="64" rx="8" fill="#0A66C2"/>
  <text x="32" y="44" font-size="32" text-anchor="middle" fill="white" font-family="sans-serif">OO</text>
</svg>
```

**Step 5: Final build**

```bash
npm run build
```

Expected: `dist/` populated, no TypeScript errors.

**Step 6: Commit**

```bash
git add nodes/ index.ts && git commit -m "feat: assemble main OpenOutreach node"
```

---

### Task 19: Local Testing of the n8n Node

**Step 1: Link the package locally**

```bash
# In n8n-nodes-openoutreach/
npm link

# In your n8n custom nodes directory (usually ~/.n8n/custom/ or configured path)
npm link n8n-nodes-openoutreach
```

**Step 2: Start n8n**

```bash
n8n start
```

**Step 3: Verify in n8n UI**

1. Open `http://localhost:5678`
2. Create a new workflow
3. Click + → search for "OpenOutreach" — should appear in node picker
4. Add credentials (Settings → Credentials → New → OpenOutreach API)
5. Point at your running OpenOutreach instance (`http://localhost:8000` for local dev)
6. Test "Profiles → Get Many" — should return `[]` on fresh DB

**Step 4: Publish to npm (when ready)**

```bash
npm publish --access public
```

Users install via n8n: **Settings → Community Nodes → Install** → `n8n-nodes-openoutreach`

---

## HTTPS Setup for Remote Deployment

### Option A: Caddy (recommended — automatic TLS)

Add to `local.yml` (Docker Compose):

```yaml
  caddy:
    image: caddy:2-alpine
    restart: unless-stopped
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile:ro
      - caddy_data:/data
      - caddy_config:/config
    depends_on:
      - openoutreach

volumes:
  caddy_data:
  caddy_config:
```

Create `Caddyfile`:

```
openoutreach.yourdomain.com {
    reverse_proxy openoutreach:8000
}
```

Start Django with gunicorn in the openoutreach service (update `Dockerfile` CMD or entrypoint):

```
gunicorn linkedin.wsgi:application --bind 0.0.0.0:8000 --workers 2
```

### Option B: Cloudflare Tunnel (zero port-forwarding)

```bash
cloudflared tunnel login
cloudflared tunnel create openoutreach
cloudflared tunnel route dns openoutreach openoutreach.yourdomain.com
cloudflared tunnel run --url http://localhost:8000 openoutreach
```

---

## Rollback Plan

All changes are additive (new app, new models, new endpoints). The daemon change adds one non-blocking function call after each tick — easily removed. To rollback Phase 1:

1. Remove `path("api/v1/", ...)` from `urls.py`
2. Remove `linkedin.rest_api` from `INSTALLED_APPS`
3. Remove `_process_action_jobs(session)` from `daemon.py`
4. Run `python manage.py migrate linkedin zero_api_models` (squash migration)

---

## Testing Strategy

- **Models**: `tests/test_api_models.py` — pure DB tests, no browser
- **Auth**: `tests/test_api_auth.py` — DRF auth class unit tests
- **Endpoints**: `tests/test_api_profiles.py`, `test_api_campaigns.py`, `test_api_jobs.py` — `APIClient` integration tests
- **Daemon**: test `_process_action_jobs` with a mock session (no Playwright needed — mock `execute()` on lane objects)
- **n8n node**: manual testing via linked local package + live OpenOutreach instance

Run all: `make test` or `pytest tests/ -v`
