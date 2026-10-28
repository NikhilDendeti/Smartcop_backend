import hmac
import secrets
from datetime import timedelta
from hashlib import sha256

from django.conf import settings
from django.core.cache import cache
from django.db.models import F
from django.utils import timezone
from rest_framework.exceptions import APIException, AuthenticationFailed, Throttled

from core.sms import SMSError, get_sms_backend
from users.models import OTPChallenge, User

INVALID_CODE = "The code is invalid or has expired."


class SMSUnavailable(APIException):
    status_code = 503
    default_detail = "We could not send the code right now. Please try again shortly."
    default_code = "sms_unavailable"


def _hash(phone, code):
    return hmac.new(settings.OTP_HASH_KEY.encode(), f"{phone}:{code}".encode(), sha256).hexdigest()


def _new_code():
    if settings.DEBUG and settings.DEV_FIXED_OTP:
        return settings.DEV_FIXED_OTP
    return f"{secrets.randbelow(10**6):06d}"


def request_otp(phone):
    """Send a login code if the number belongs to a user. The caller gets the same answer either
    way, so the endpoint cannot be used to discover which numbers are registered."""
    cooldown_key = f"otp-cooldown:{phone}"
    if not cache.add(cooldown_key, 1, settings.OTP_RESEND_COOLDOWN_SECONDS):
        raise Throttled(wait=settings.OTP_RESEND_COOLDOWN_SECONDS)

    if not User.objects.filter(phone=phone).exists():
        return

    now = timezone.now()
    OTPChallenge.objects.filter(phone=phone, consumed_at__isnull=True).update(consumed_at=now)

    code = _new_code()
    challenge = OTPChallenge.objects.create(
        phone=phone,
        code_hash=_hash(phone, code),
        expires_at=now + timedelta(seconds=settings.OTP_TTL_SECONDS),
        max_attempts=settings.OTP_MAX_ATTEMPTS,
    )
    minutes = settings.OTP_TTL_SECONDS // 60
    try:
        get_sms_backend().send(phone, f"Your SmartCop login code is {code}. It expires in {minutes} minutes.")
    except SMSError:
        challenge.delete()
        cache.delete(cooldown_key)
        raise SMSUnavailable()


def verify_otp(phone, code):
    """Check a code and return its user. A code works once and only for a limited number of tries."""
    challenge = (
        OTPChallenge.objects.filter(phone=phone, purpose="login", consumed_at__isnull=True)
        .order_by("-created_at")
        .first()
    )
    if challenge is None or not challenge.is_usable:
        raise AuthenticationFailed(INVALID_CODE)

    # Count the attempt first, so a wrong guess is recorded even though we then raise.
    OTPChallenge.objects.filter(pk=challenge.pk).update(attempts=F("attempts") + 1)

    if not hmac.compare_digest(challenge.code_hash, _hash(phone, code)):
        raise AuthenticationFailed(INVALID_CODE)

    # Atomic single use: only one concurrent request can flip consumed_at.
    claimed = OTPChallenge.objects.filter(pk=challenge.pk, consumed_at__isnull=True).update(
        consumed_at=timezone.now()
    )
    if not claimed:
        raise AuthenticationFailed(INVALID_CODE)

    user = User.objects.filter(phone=phone).first()
    if user is None:
        raise AuthenticationFailed(INVALID_CODE)
    return user
