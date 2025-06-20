from users.models import User, Complaint
from police.models import OfficerRole, CaseAssignment, CaseProgress

class AssignComplaintToHCInteractor:
    def __init__(self, complaint_id, hc_phone, si_phone, notes=""):
        self.complaint_id = complaint_id
        self.hc_phone = hc_phone
        self.si_phone = si_phone
        self.notes = notes

    def execute(self):
        try:
            complaint = Complaint.objects.get(complaint_id=self.complaint_id)
        except Complaint.DoesNotExist:
            raise ValueError("Complaint not found")

        try:
            hc_user = User.objects.get(phone=self.hc_phone)
            hc_role = OfficerRole.objects.get(officer=hc_user, designation='head_constable')
        except (User.DoesNotExist, OfficerRole.DoesNotExist):
            raise ValueError("Head Constable not found or role mismatch")

        try:
            si_user = User.objects.get(phone=self.si_phone)
            si_role = OfficerRole.objects.get(officer=si_user, designation='sub_inspector')
        except (User.DoesNotExist, OfficerRole.DoesNotExist):
            raise ValueError("Sub-Inspector not found or role mismatch")

        # Create case assignment
        CaseAssignment.objects.create(
            complaint=complaint,
            assigned_by=si_user,
            assigned_to=hc_user,
            role_at_assignment='head_constable',
            notes=self.notes
        )

        # Add progress update
        CaseProgress.objects.create(
            complaint=complaint,
            stage='assigned_to_officer',
            updated_by=si_user,
            remarks=self.notes
        )

        return {
            "status": "success",
            "message": f"Complaint assigned to Head Constable {hc_user.name}.",
            "assigned_to": {
                "name": hc_user.name,
                "phone": hc_user.phone
            }
        }
