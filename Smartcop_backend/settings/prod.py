import os

from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F401,F403
from .base import ALLOWED_HOSTS, CORS_ALLOWED_ORIGINS, DATABASES, FIELD_ENCRYPTION_KEY

DEBUG = False

if not FIELD_ENCRYPTION_KEY:
    raise ImproperlyConfigured("Set FIELD_ENCRYPTION_KEY; personal data cannot be stored without it.")

if not ALLOWED_HOSTS or "*" in ALLOWED_HOSTS:
    raise ImproperlyConfigured("Set ALLOWED_HOSTS to the exact hostnames served in production.")

if not CORS_ALLOWED_ORIGINS:
    raise ImproperlyConfigured("Set CORS_ALLOWED_ORIGINS to the production frontend origin.")

if DATABASES["default"]["ENGINE"].endswith("sqlite3"):
    raise ImproperlyConfigured("Set DATABASE_URL to a PostgreSQL database in production.")

if os.environ.get("DEV_FIXED_OTP"):
    raise ImproperlyConfigured("DEV_FIXED_OTP must not be set in production.")

# Secure by default: no SMS means no logins, and the unauthenticated legacy routes stay off.
SMS_BACKEND = os.environ.get("SMS_BACKEND", "core.sms.UnconfiguredSMSBackend")
LEGACY_API_ENABLED = os.environ.get("LEGACY_API_ENABLED", "false").lower() == "true"

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = True
# Load balancers and the container health check probe over plain HTTP; they must not be redirected.
SECURE_REDIRECT_EXEMPT = [r"^health/$", r"^ready/$"]
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
