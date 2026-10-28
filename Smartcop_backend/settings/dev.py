import base64
import hashlib
import os

from .base import *  # noqa: F401,F403
from .base import DEV_FIXED_OTP, FIELD_ENCRYPTION_KEY, REST_FRAMEWORK, SECRET_KEY, env_list

DEBUG = True

# Local work has no virus scanner, so let files through; production leaves this off.
EVIDENCE_ALLOW_UNSCANNED = os.environ.get("EVIDENCE_ALLOW_UNSCANNED", "true").lower() == "true"

ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", "localhost,127.0.0.1,[::1]")

CORS_ALLOWED_ORIGINS = env_list(
    "CORS_ALLOWED_ORIGINS",
    "http://localhost:8080,http://localhost:3000,http://localhost:5173,http://localhost:4173",
)

# With a fixed login code (local work and end-to-end tests) people log in many times in a row, so
# lift the resend cooldown and the login rate limits. They stay fully in force without DEV_FIXED_OTP.
if DEV_FIXED_OTP:
    OTP_RESEND_COOLDOWN_SECONDS = 0
    REST_FRAMEWORK = {
        **REST_FRAMEWORK,
        "DEFAULT_THROTTLE_RATES": {**REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"], "otp_ip": "10000/hour",
                                   "otp_phone": "10000/hour", "otp_verify_phone": "10000/hour"},
    }

# Local convenience only: derive an encryption key from SECRET_KEY when none is configured.
if not FIELD_ENCRYPTION_KEY:
    FIELD_ENCRYPTION_KEY = base64.urlsafe_b64encode(hashlib.sha256(SECRET_KEY.encode()).digest()).decode()
