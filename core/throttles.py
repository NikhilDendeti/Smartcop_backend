from rest_framework.throttling import AnonRateThrottle, SimpleRateThrottle, UserRateThrottle


class PhoneRateThrottle(SimpleRateThrottle):
    """Limits requests per phone number in the body, so one number cannot be hammered from many IPs."""

    def get_cache_key(self, request, view):
        phone = str(request.data.get("phone", "")).strip()
        if not phone:
            return None
        return self.cache_format % {"scope": self.scope, "ident": phone}


class OTPRequestIPThrottle(AnonRateThrottle):
    scope = "otp_ip"


class OTPRequestPhoneThrottle(PhoneRateThrottle):
    scope = "otp_phone"


class OTPVerifyPhoneThrottle(PhoneRateThrottle):
    scope = "otp_verify_phone"


class AIRateThrottle(UserRateThrottle):
    """AI calls cost money, so each user gets a budget."""

    scope = "ai"
