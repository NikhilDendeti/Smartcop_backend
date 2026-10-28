import base64
import hashlib

from .base import *  # noqa: F401,F403
from .base import FIELD_ENCRYPTION_KEY, SECRET_KEY, env_list

DEBUG = True

ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", "localhost,127.0.0.1,[::1]")

CORS_ALLOWED_ORIGINS = env_list("CORS_ALLOWED_ORIGINS", "http://localhost:8080,http://localhost:3000")

# Local convenience only: derive an encryption key from SECRET_KEY when none is configured.
if not FIELD_ENCRYPTION_KEY:
    FIELD_ENCRYPTION_KEY = base64.urlsafe_b64encode(hashlib.sha256(SECRET_KEY.encode()).digest()).decode()
