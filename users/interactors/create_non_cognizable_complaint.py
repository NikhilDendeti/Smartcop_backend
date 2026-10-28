from users.models import Complaint, AIAssessment, CaseType
from users.utils.ai_predictor import get_ai_assessment
from django.utils import timezone

class CreateNonCognizableComplaintInteractor:
    def __init__(self, data):
        self.data = data

    def create(self):
        user_id = self.data.get("user_id")
        summary = self.data.get("incident_summary")
        case_type_name = self.data.get("case_type")

        # Fetch CaseType
        case_type = CaseType.objects.get(name=case_type_name)

        # Step 1: AI Assessment (still used for IPC only)
        ai_result = get_ai_assessment(summary)
        ipc_sections = ai_result.get("ipc_sections", {})

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

        # Step 3: Attach AI Assessment (without urgency)
        AIAssessment.objects.create(
            complaint=complaint,
            ipc_sections=ipc_sections,
            ipc_descriptions=ipc_sections,
            urgency_score=0,
            model_version="SmartCop-v1",
            generated_at=timezone.now()
        )

        return {
            "message": "This is a non-cognizable case. It has been recorded in the General Diary (GD). Police cannot take action without magistrate's permission.",
            "ipc_sections": ipc_sections,
            "complaint_id": str(complaint.complaint_id),
            "status": "gd_recorded"
        }
