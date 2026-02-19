from rest_framework.permissions import BasePermission


class HasApiKey(BasePermission):
    """Allow any request authenticated via ApiKeyAuthentication (request.auth is set)."""

    message = "A valid API key is required."

    def has_permission(self, request, view):
        return request.auth is not None
