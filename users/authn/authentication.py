from rest_framework.authentication import BaseAuthentication, get_authorization_header
from rest_framework.exceptions import AuthenticationFailed

from users.authn.tokens import INVALID, decode_token
from users.models import User


class NoCredentials(BaseAuthentication):
    """For the login endpoints, which take no token. Declaring a challenge header makes a
    failed login answer 401 instead of DRF's fallback of 403."""

    def authenticate(self, request):
        return None

    def authenticate_header(self, request):
        return 'Bearer realm="smartcop"'


class JWTAuthentication(BaseAuthentication):
    """Authenticates `Authorization: Bearer <access token>`. The user is loaded on every request,
    so a change to someone's role takes effect immediately rather than when their token expires."""

    def authenticate(self, request):
        parts = get_authorization_header(request).split()
        if not parts or parts[0].lower() != b"bearer":
            return None
        if len(parts) != 2:
            raise AuthenticationFailed("Invalid Authorization header.")

        claims = decode_token(parts[1].decode(), "access")
        try:
            user = User.objects.get(pk=claims["sub"])
        except (User.DoesNotExist, ValueError):
            raise AuthenticationFailed(INVALID)
        return user, claims

    def authenticate_header(self, request):
        return 'Bearer realm="smartcop"'
