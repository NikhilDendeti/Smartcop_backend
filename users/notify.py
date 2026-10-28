"""In-app notifications. Delivery over SMS or push plugs in here later; for now every message is
stored for the recipient to read through the notifications endpoint."""

from users.models import Notification


def notify(user, event, message, complaint=None):
    return Notification.objects.create(
        user=user, complaint=complaint, channel="in_app", event=event, message=message
    )


def notify_officers(designations, station, event, message, complaint=None):
    """Notify every active officer with one of the designations at a station."""
    from police.models import OfficerRole

    roles = OfficerRole.objects.filter(
        designation__in=designations, station=station, is_active=True
    ).select_related("officer")
    return [notify(role.officer, event, message, complaint) for role in roles]


def notify_magistrates(event, message, complaint=None):
    from users.models import User

    return [notify(user, event, message, complaint) for user in User.objects.filter(role="magistrate")]
