"""DRF throttle class keyed by API key hash."""
from rest_framework.throttling import SimpleRateThrottle


class ApiKeyThrottle(SimpleRateThrottle):
    """Rate-limits requests per API key. Scope: 'api_key'."""

    scope = "api_key"

    def get_cache_key(self, request, view):
        if request.auth is None:
            # Unauthenticated requests: do not throttle here
            # (they will be rejected by HasApiKey before reaching the view body)
            return None
        return f"throttle_apikey_{request.auth.key_hash}"
