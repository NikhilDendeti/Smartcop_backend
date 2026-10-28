from rest_framework.exceptions import APIException

from users.models import ConsentRecord

AI_PROCESSING = "ai_processing"


class ConsentRequired(APIException):
    status_code = 403
    default_detail = "The citizen has not agreed to AI-assisted processing."
    default_code = "consent_required"


def has_consent(user, purpose=AI_PROCESSING) -> bool:
    """True if the user's most recent consent for this purpose is still in force."""
    latest = ConsentRecord.objects.filter(user=user, purpose=purpose).order_by("-granted_at").first()
    return latest is not None and latest.revoked_at is None


def require_consent(user, purpose=AI_PROCESSING):
    if not has_consent(user, purpose):
        raise ConsentRequired()
