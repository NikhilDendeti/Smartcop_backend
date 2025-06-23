from users.models import Complaint, AIAssessment
from police.models import *

class ListAllComplaintsInteractor:
    def execute(self):
        complaints = Complaint.objects.all().select_related('user', 'case_type', 'assessment')
        data = []

        for complaint in complaints:
            latest_stage = (
                complaint.progress_updates.last().get_stage_display()
                if complaint.progress_updates.exists() else "Not Started"
            )

            # Safely access AI assessment fields
            assessment = getattr(complaint, 'assessment', None)
            ai_score = assessment.urgency_score if assessment else None
            ipc_sections = assessment.ipc_sections if assessment else {}

            data.append({
                "complaint_id": str(complaint.complaint_id),
                "user": {
                    "name": complaint.user.name,
                    "phone": complaint.user.phone
                },
                "case_type": complaint.case_type.name if complaint.case_type else "Unknown",
                "status": complaint.status,
                "current_stage": latest_stage,
                "ai_urgency_score": ai_score,
                "ipc_sections": ipc_sections,
                "created_at": complaint.created_at.isoformat()
            })

        return {
            "status": "success",
            "complaints": data
        }
