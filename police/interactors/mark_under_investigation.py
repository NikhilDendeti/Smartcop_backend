from users.models import Complaint, User
from police.models import OfficerRole, CaseProgress

class MarkUnderInvestigationInteractor:
    def __init__(self, complaint_id, si_phone=None, remarks="", actor=None):
        self.complaint_id = complaint_id
        self.si_phone = si_phone
        self.remarks = remarks
        # An already-authorised officer. When given, no phone lookup or SI-only check is made.
        self.actor = actor

    def execute(self):
        try:
            complaint = Complaint.objects.get(complaint_id=self.complaint_id)
        except Complaint.DoesNotExist:
            raise ValueError("Complaint not found")

        if self.actor is not None:
            si_user = self.actor
        else:
            try:
                si_user = User.objects.get(phone=self.si_phone)
                si_role = OfficerRole.objects.get(officer=si_user, designation='sub_inspector')
            except (User.DoesNotExist, OfficerRole.DoesNotExist):
                raise ValueError("SI not found or invalid role")

        CaseProgress.objects.create(
            complaint=complaint,
            stage='under_investigation',
            updated_by=si_user,
            remarks=self.remarks
        )

        return {
            "status": "success",
            "message": "Complaint marked as under investigation.",
            "complaint_id": str(complaint.complaint_id)
        }
