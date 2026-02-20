from rest_framework.permissions import BasePermission


class HasApiKey(BasePermission):
    """
    Grants access if the request carries a valid API key (request.auth is set
    by ApiKeyAuthentication).

    Single-tenant design: all valid API keys have equal access to all resources.
    There is no per-key data scoping. This is intentional for a self-hosted,
    single-operator deployment. If you issue API keys to multiple untrusted
    parties, add campaign-level scoping to the ApiKey model.
    """

    message = "A valid API key is required."

    def has_permission(self, request, view):
        return request.auth is not None
