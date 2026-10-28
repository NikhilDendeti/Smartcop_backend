from users.models import Complaint, AIAssessment
from police.models import *

class ListAllComplaintsInteractor:
    def __init__(self, queryset=None):
        # Callers acting for a person pass users.access.complaints_for(user); None means everything.
        self.queryset = queryset

    @staticmethod
    def prepare(queryset):
        """Load what rows() needs in a fixed number of queries, however many complaints there are."""
        return queryset.select_related('user', 'case_type', 'assessment').prefetch_related('progress_updates')

    def rows(self, complaints):
        data = []

        for complaint in complaints:
            updates = list(complaint.progress_updates.all())
            latest_stage = updates[-1].get_stage_display() if updates else "Not Started"

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
                "ai_status": assessment.ai_status if assessment else None,
                "needs_review": assessment.needs_review if assessment else None,
                "ipc_sections": ipc_sections,
                "created_at": complaint.created_at.isoformat()
            })
        return data

    def execute(self):
        queryset = self.queryset if self.queryset is not None else Complaint.objects.all()
        return {
            "status": "success",
            "complaints": self.rows(self.prepare(queryset))
        }
