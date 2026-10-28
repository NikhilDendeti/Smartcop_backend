"""Who a user is acting as, and which complaints that role may see.

Every complaint query made on behalf of a person must go through complaints_for()."""

from django.db.models import Q

from users.models import Complaint

CITIZEN = "citizen"
HEAD_CONSTABLE = "head_constable"
SUB_INSPECTOR = "sub_inspector"
SHO = "sho"
MAGISTRATE = "magistrate"
ADMIN = "admin"

OFFICER_ROLES = (HEAD_CONSTABLE, SUB_INSPECTOR, SHO)
COMMAND_ROLES = (SUB_INSPECTOR, SHO)


def officer_profile(user):
    """The user's OfficerRole, or None when they have none."""
    return getattr(user, "officerrole", None)


def actor_role(user):
    """The single role a user acts under, or None when they have no usable access."""
    if user.role == "officer":
        profile = officer_profile(user)
        return profile.designation if profile and profile.is_active else None
    return user.role


def complaints_for(user):
    """Complaints this user is allowed to see. Admins deliberately see none."""
    role = actor_role(user)
    complaints = Complaint.objects.all()

    if role == CITIZEN:
        return complaints.filter(user=user)
    if role == HEAD_CONSTABLE:
        return complaints.filter(Q(officer_assigned=user) | Q(assignments__assigned_to=user)).distinct()
    if role in COMMAND_ROLES:
        return complaints.filter(station=officer_profile(user).station)
    if role == MAGISTRATE:
        return complaints.filter(magistrate_approval__isnull=False)
    return complaints.none()
