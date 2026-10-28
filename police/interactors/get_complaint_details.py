from users.models import Complaint
from police.models import *
from django.core.exceptions import ObjectDoesNotExist

class GetComplaintDetailsInteractor:
    def __init__(self, complaint_id):
        self.complaint_id = complaint_id

    def execute(self):
        try:
            complaint = Complaint.objects.select_related('user', 'case_type').get(complaint_id=self.complaint_id)
        except ObjectDoesNotExist:
            return {
                "status": "failed",
                "error": "Complaint not found"
            }

        timeline = []
        for progress in complaint.progress_updates.all():
            timeline.append({
                "stage": progress.get_stage_display(),
                "timestamp": progress.timestamp.isoformat(),
                "updated_by": progress.updated_by.name if progress.updated_by else "System"
            })

        return {
            "status": "success",
            "complaint_id": str(complaint.complaint_id),
            "user": {
                "name": complaint.user.name,
                "phone": complaint.user.phone,
                "aadhar": complaint.user.aadhar_masked,
            },
            "case_type": complaint.case_type.name if complaint.case_type else "Unknown",
            "status": complaint.status,
            "description": complaint.incident_summary,
            "location": complaint.location,
            "created_at": complaint.created_at.isoformat(),
            "current_stage": timeline[-1]["stage"] if timeline else "Not Started",
            "progress_timeline": timeline
        }
