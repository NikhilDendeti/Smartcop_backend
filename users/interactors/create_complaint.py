from users.models import Complaint, Evidence, Accused, Witness, AIAssessment, CaseType
from users.utils.ai_predictor import get_ai_assessment

class CreateComplaintInteractor:
    def __init__(self, data, user):
        self.data = data
        self.user = user

    def execute(self):
        incident_summary = self.data.get("incident_summary")
        case_type_name = self.data.get("case_type")
        location = self.data.get("location")
        incident_date = self.data.get("incident_date")
        incident_time = self.data.get("incident_time")
        is_cognizable = self.data.get("is_cognizable", True)

        case_type_obj = CaseType.objects.get(name=case_type_name)

        ai_result = get_ai_assessment(incident_summary)
        ipc_sections = ai_result.get("ipc_sections", {})
        ai_score = ai_result.get("AI_urgency_score", 50)

        complaint = Complaint.objects.create(
            user=self.user,
            case_type=case_type_obj,
            is_cognizable=is_cognizable,
            incident_date=incident_date,
            incident_time=incident_time,
            location=location,
            incident_summary=incident_summary,
            ai_urgency_score=ai_score,
            station=self.data.get("station")
        )

        AIAssessment.objects.create(
            complaint=complaint,
            ipc_sections=ipc_sections,
            ipc_descriptions=ipc_sections,
            urgency_score=ai_score,
            model_version="gpt-4-0613-preview"
        )

        for acc in self.data.get("accused", []):
            Accused.objects.create(
                complaint=complaint,
                name=acc.get("name"),
                description=acc.get("description"),
                contact_info=acc.get("contact_info"),
                statement=acc.get("statement")
            )

        for wit in self.data.get("witnesses", []):
            Witness.objects.create(
                complaint=complaint,
                name=wit.get("name"),
                contact_info=wit.get("contact_info"),
                statement=wit.get("statement")
            )

        for ev in self.data.get("evidence", []):
            Evidence.objects.create(
                complaint=complaint,
                file_url=ev.get("file_url"),
                type=ev.get("type")
            )

        return complaint