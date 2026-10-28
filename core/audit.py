import logging

from django.conf import settings

from core.models import AuditLog
from core.request_context import get_request_id

logger = logging.getLogger(__name__)


def client_ip(request):
    if getattr(settings, "TRUST_X_FORWARDED_FOR", False):
        forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def record(request, action, resource_type, resource_id="", outcome="allowed", metadata=None, actor=None):
    """Append an entry to the audit log. The actor defaults to the authenticated request user."""
    from users.access import actor_role

    user = actor
    if user is None:
        candidate = getattr(request, "user", None)
        user = candidate if getattr(candidate, "is_authenticated", False) else None

    return AuditLog.objects.create(
        actor=user,
        actor_role=(actor_role(user) or "") if user else "",
        action=action,
        resource_type=resource_type,
        resource_id=str(resource_id)[:64],
        outcome=outcome,
        metadata=metadata or {},
        ip_address=client_ip(request),
        request_id=get_request_id()[:64],
    )


def record_denied(request, reason):
    """Log a forbidden request. A failure here must never turn a 403 into a 500."""
    try:
        record(
            request,
            "access_denied",
            "endpoint",
            request.path,
            outcome="denied",
            metadata={"method": request.method, "reason": str(reason)},
        )
    except Exception:
        logger.exception("Could not write access-denied audit entry")
