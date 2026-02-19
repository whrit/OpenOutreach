# linkedin/models.py
import hashlib
import secrets

from django.contrib.auth.models import User
from django.db import models


class Campaign(models.Model):
    department = models.OneToOneField(
        "common.Department",
        on_delete=models.CASCADE,
        related_name="campaign",
    )
    product_docs = models.TextField(blank=True)
    campaign_objective = models.TextField(blank=True)
    followup_template = models.TextField(blank=True)
    booking_link = models.URLField(max_length=500, blank=True)
    is_partner = models.BooleanField(default=False)
    action_fraction = models.FloatField(default=0.0)

    def __str__(self):
        return self.department.name

    class Meta:
        app_label = "linkedin"


class LinkedInProfile(models.Model):
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="linkedin_profile",
    )
    linkedin_username = models.CharField(max_length=200)
    linkedin_password = models.CharField(max_length=200)
    subscribe_newsletter = models.BooleanField(default=True)
    active = models.BooleanField(default=True)
    connect_daily_limit = models.PositiveIntegerField(default=20)
    connect_weekly_limit = models.PositiveIntegerField(default=100)
    follow_up_daily_limit = models.PositiveIntegerField(default=30)

    def __str__(self):
        return f"{self.user.username} ({self.linkedin_username})"

    class Meta:
        app_label = "linkedin"


class SearchKeyword(models.Model):
    campaign = models.ForeignKey(
        Campaign,
        on_delete=models.CASCADE,
        related_name="search_keywords",
    )
    keyword = models.CharField(max_length=500)
    used = models.BooleanField(default=False)
    used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        app_label = "linkedin"
        unique_together = [("campaign", "keyword")]

    def __str__(self):
        return self.keyword


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
    events = models.JSONField(default=list)
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
