from users.models import Complaint
from users.progress import status_fields


class GetUserComplaintsInteractor:
    def __init__(self, user_id):
        self.user_id = user_id

    def execute(self):
        complaints = (
            Complaint.objects.filter(user_id=self.user_id)
            .select_related('case_type', 'assessment')
            .order_by('-created_at')
        )
        rows = []
        for comp in complaints:
            assessment = getattr(comp, 'assessment', None)
            rows.append({
                "complaint_id": str(comp.complaint_id),
                "case_type": comp.case_type.name,
                "status": comp.status,
                **status_fields(comp.status),
                "incident_summary": comp.incident_summary,
                "incident_date": comp.incident_date,
                "created_at": comp.created_at.isoformat(),
                "ai_status": assessment.ai_status if assessment else None,
            })
        return rows
