from users.models import User
from police.models import OfficerRole

class ListHeadConstablesInteractor:
    def __init__(self, si_phone=None, actor=None):
        self.si_phone = si_phone
        # An already-authorised commanding officer; Head Constables are then matched by station.
        self.actor = actor

    def execute(self):
        if self.actor is not None:
            head_constables = OfficerRole.objects.filter(
                designation='head_constable',
                station=self.actor.officerrole.station,
                is_active=True,
            ).select_related("officer")
        else:
            try:
                si_user = User.objects.get(phone=self.si_phone)
                si_role = OfficerRole.objects.get(officer=si_user, designation='sub_inspector')
            except (User.DoesNotExist, OfficerRole.DoesNotExist):
                raise ValueError("SI not found or role mismatch")

            # Filter Head Constables in same department as SI
            head_constables = OfficerRole.objects.filter(
                designation='head_constable',
                department=si_role.department
            ).select_related("officer")

        return {
            "status": "success",
            "head_constables": [
                {
                    "user_id": str(role.officer.user_id),
                    "name": role.officer.name,
                    "phone": role.officer.phone,
                    "department": role.department
                }
                for role in head_constables
            ]
        }
