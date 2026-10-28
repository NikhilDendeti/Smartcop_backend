from django.db import transaction

from ai.assessment import enqueue_assessment
from ai.services import create_pending_assessment
from police.models import CaseProgress
from users.models import Complaint, CaseType

class CreateNonCognizableComplaintInteractor:
    def __init__(self, data):
        self.data = data

    def create(self):
        user_id = self.data.get("user_id")
        summary = self.data.get("incident_summary")
        case_type_name = self.data.get("case_type")

        case_type = CaseType.objects.get(name=case_type_name)

        # Saved together or not at all. The AI analysis (legal sections only; no urgency for a GD
        # entry) runs in the background once the complaint is safely stored.
        with transaction.atomic():
            complaint = Complaint.objects.create(
                user_id=user_id,
                case_type=case_type,
                incident_summary=summary,
                incident_date=self.data.get("incident_date"),
                incident_time=self.data.get("incident_time"),
                location=self.data.get("location"),
                is_cognizable=False,
                status="gd_recorded",
                station=self.data.get("station"),
            )
            create_pending_assessment(complaint)
            CaseProgress.objects.create(
                complaint=complaint, stage="gd_recorded", updated_by_id=user_id, remarks="Recorded in the General Diary"
            )
            transaction.on_commit(lambda: enqueue_assessment(complaint.pk))

        return {
            "message": "This is a non-cognizable case. It has been recorded in the General Diary (GD). Police cannot take action without magistrate's permission.",
            "complaint_id": str(complaint.complaint_id),
            "status": "gd_recorded",
            "ai_status": "pending",
        }
