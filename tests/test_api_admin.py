"""Tests for Django admin registrations of ApiKey, ActionJob, WebhookSubscription."""
import pytest
from django.contrib import admin

from linkedin.models import ActionJob, ApiKey, WebhookSubscription


def test_apikey_admin_registered():
    assert ApiKey in admin.site._registry


def test_actionjob_admin_registered():
    assert ActionJob in admin.site._registry


def test_webhooksubscription_admin_registered():
    assert WebhookSubscription in admin.site._registry


def test_apikey_admin_list_display():
    model_admin = admin.site._registry[ApiKey]
    assert "name" in model_admin.list_display
    assert "active" in model_admin.list_display
    assert "created_at" in model_admin.list_display


def test_actionjob_admin_list_display():
    model_admin = admin.site._registry[ActionJob]
    assert "id" in model_admin.list_display
    assert "lane" in model_admin.list_display
    assert "status" in model_admin.list_display
    assert "campaign" in model_admin.list_display


def test_apikey_admin_key_hash_readonly():
    model_admin = admin.site._registry[ApiKey]
    assert "key_hash" in model_admin.readonly_fields
