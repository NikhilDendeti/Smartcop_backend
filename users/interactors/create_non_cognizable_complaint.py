from django.db import transaction

from ai.classification import classify_incident
from ai.services import save_assessment
from police.models import CaseProgress
from users.models import Complaint, CaseType

class CreateNonCognizableComplaintInteractor:
    def __init__(self, data):
        self.data = data

    def create(self):
        user_id = self.data.get("user_id")
        summary = self.data.get("incident_summary")
        case_type_name = self.data.get("case_type")

        # Fetch CaseType
        case_type = CaseType.objects.get(name=case_type_name)

        # Step 1: AI Assessment (legal sections only; no urgency for a GD entry)
        ai_result = classify_incident(summary, self.data.get("incident_date"))
        ipc_sections = ai_result.section_map

        # Steps 2 and 3 are saved together or not at all.
        with transaction.atomic():
            # Step 2: Create Complaint with GD (not FIR)
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

            # Step 3: Attach AI Assessment (without urgency) and start the timeline
            save_assessment(complaint, ai_result, urgency_override=0)
            CaseProgress.objects.create(
                complaint=complaint, stage="gd_recorded", updated_by_id=user_id, remarks="Recorded in the General Diary"
            )

        return {
            "message": "This is a non-cognizable case. It has been recorded in the General Diary (GD). Police cannot take action without magistrate's permission.",
            "ipc_sections": ipc_sections,
            "complaint_id": str(complaint.complaint_id),
            "status": "gd_recorded",
            "ai_status": ai_result.status,
            "needs_review": ai_result.needs_review,
        }
