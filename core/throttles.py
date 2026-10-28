import logging

from rest_framework.throttling import AnonRateThrottle, SimpleRateThrottle, UserRateThrottle

from core.exceptions import ServiceUnavailable

logger = logging.getLogger(__name__)


class ResilientThrottleMixin:
    """Rate limits live in the cache. If it is down, security-sensitive limits (login codes) refuse
    the request with a 503 rather than silently allowing unlimited guesses; limits that only
    protect cost (AI calls) let the request through, because the AI budget is enforced separately."""

    fail_open = False

    def allow_request(self, request, view):
        try:
            return super().allow_request(request, view)
        except Exception:
            logger.exception("Rate limiter unavailable (%s)", self.scope)
            if self.fail_open:
                return True
            raise ServiceUnavailable() from None


class PhoneRateThrottle(ResilientThrottleMixin, SimpleRateThrottle):
    """Limits requests per phone number in the body, so one number cannot be hammered from many IPs."""

    def get_cache_key(self, request, view):
        phone = str(request.data.get("phone", "")).strip()
        if not phone:
            return None
        return self.cache_format % {"scope": self.scope, "ident": phone}


class OTPRequestIPThrottle(ResilientThrottleMixin, AnonRateThrottle):
    scope = "otp_ip"


class OTPRequestPhoneThrottle(PhoneRateThrottle):
    scope = "otp_phone"


class OTPVerifyPhoneThrottle(PhoneRateThrottle):
    scope = "otp_verify_phone"


class AIRateThrottle(ResilientThrottleMixin, UserRateThrottle):
    """AI calls cost money, so each user gets a budget."""

    scope = "ai"
    fail_open = True
