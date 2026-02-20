"""
Tests for DRF global settings in django_settings.py.
"""
from django.conf import settings


def test_drf_auth_class_configured():
    auth_classes = settings.REST_FRAMEWORK.get("DEFAULT_AUTHENTICATION_CLASSES", [])
    assert "linkedin.rest_api.authentication.ApiKeyAuthentication" in auth_classes


def test_drf_permission_class_configured():
    permission_classes = settings.REST_FRAMEWORK.get("DEFAULT_PERMISSION_CLASSES", [])
    assert "linkedin.rest_api.permissions.HasApiKey" in permission_classes


def test_drf_json_renderer_only():
    renderer_classes = settings.REST_FRAMEWORK.get("DEFAULT_RENDERER_CLASSES", [])
    assert renderer_classes == ["rest_framework.renderers.JSONRenderer"]


def test_drf_unauthenticated_user_none():
    assert settings.REST_FRAMEWORK.get("UNAUTHENTICATED_USER") is None


def test_throttle_class_configured():
    auth_classes = settings.REST_FRAMEWORK.get("DEFAULT_THROTTLE_CLASSES", [])
    assert any("ApiKeyThrottle" in c for c in auth_classes)


def test_throttle_rate_configured():
    rates = settings.REST_FRAMEWORK.get("DEFAULT_THROTTLE_RATES", {})
    assert "api_key" in rates
