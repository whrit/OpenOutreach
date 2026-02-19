from django.contrib.auth.models import AnonymousUser
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed

from linkedin.models import ApiKey


class ApiKeyAuthentication(BaseAuthentication):
    """Authenticate via 'Authorization: Api-Key <raw_token>' header."""

    keyword = "Api-Key"

    def authenticate(self, request):
        auth_header = request.META.get("HTTP_AUTHORIZATION", "")
        if not auth_header.startswith(f"{self.keyword} "):
            return None  # No Api-Key header — try next authenticator

        raw_token = auth_header[len(f"{self.keyword} "):]
        if not raw_token:
            raise AuthenticationFailed("Empty API key.")

        api_key = ApiKey.authenticate(raw_token)
        if not api_key:
            raise AuthenticationFailed("Invalid or inactive API key.")

        # DRF expects (user, token). Return the api_key as the token (request.auth).
        # We return AnonymousUser as user — views use request.auth to identify the key.
        return (AnonymousUser(), api_key)

    def authenticate_header(self, request):
        return self.keyword
