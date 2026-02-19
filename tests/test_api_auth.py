import pytest
from rest_framework.test import APIRequestFactory
from rest_framework.exceptions import AuthenticationFailed

from linkedin.models import ApiKey
from linkedin.rest_api.authentication import ApiKeyAuthentication
from linkedin.rest_api.permissions import HasApiKey


@pytest.mark.django_db
def test_valid_api_key_authenticates():
    _, raw = ApiKey.generate("test")
    factory = APIRequestFactory()
    request = factory.get("/", HTTP_AUTHORIZATION=f"Api-Key {raw}")
    auth = ApiKeyAuthentication()
    result = auth.authenticate(request)
    assert result is not None
    user, key = result
    assert key is not None
    assert key.name == "test"


@pytest.mark.django_db
def test_invalid_api_key_raises():
    factory = APIRequestFactory()
    request = factory.get("/", HTTP_AUTHORIZATION="Api-Key badtoken12345")
    auth = ApiKeyAuthentication()
    with pytest.raises(AuthenticationFailed):
        auth.authenticate(request)


def test_missing_header_returns_none():
    factory = APIRequestFactory()
    request = factory.get("/")
    auth = ApiKeyAuthentication()
    assert auth.authenticate(request) is None


def test_wrong_prefix_returns_none():
    factory = APIRequestFactory()
    request = factory.get("/", HTTP_AUTHORIZATION="Bearer sometoken")
    auth = ApiKeyAuthentication()
    assert auth.authenticate(request) is None


@pytest.mark.django_db
def test_has_api_key_permission_with_valid_auth():
    _, raw = ApiKey.generate("perm-test")
    factory = APIRequestFactory()
    request = factory.get("/", HTTP_AUTHORIZATION=f"Api-Key {raw}")

    # Simulate DRF authentication step
    auth = ApiKeyAuthentication()
    request.auth = None
    result = auth.authenticate(request)
    if result:
        request.auth = result[1]

    perm = HasApiKey()
    assert perm.has_permission(request, None) is True


def test_has_api_key_permission_denied_no_auth():
    factory = APIRequestFactory()
    request = factory.get("/")
    request.auth = None
    perm = HasApiKey()
    assert perm.has_permission(request, None) is False
