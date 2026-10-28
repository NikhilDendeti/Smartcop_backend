from rest_framework.permissions import BasePermission

from users import access


class HasRole(BasePermission):
    """Allows authenticated users whose acting role is in allowed_roles."""

    allowed_roles: tuple = ()

    def has_permission(self, request, view):
        user = request.user
        return bool(
            user
            and getattr(user, "is_authenticated", False)
            and access.actor_role(user) in self.allowed_roles
        )


def roles(name, *allowed):
    return type(name, (HasRole,), {"allowed_roles": allowed})


IsCitizen = roles("IsCitizen", access.CITIZEN)
IsAdminRole = roles("IsAdminRole", access.ADMIN)
IsOfficer = roles("IsOfficer", *access.OFFICER_ROLES)
IsCommander = roles("IsCommander", *access.COMMAND_ROLES)
IsMagistrate = roles("IsMagistrate", access.MAGISTRATE)
IsCaseParticipant = roles("IsCaseParticipant", *access.OFFICER_ROLES, access.MAGISTRATE)
IsAnyRole = roles(
    "IsAnyRole", access.CITIZEN, *access.OFFICER_ROLES, access.MAGISTRATE, access.ADMIN
)
