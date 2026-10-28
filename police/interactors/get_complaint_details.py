from users.models import Complaint
from police.models import *
from django.core.exceptions import ObjectDoesNotExist

class GetComplaintDetailsInteractor:
    def __init__(self, complaint_id, actor=None):
        self.complaint_id = complaint_id
        # When given, the response lists the status changes this officer may make next.
        self.actor = actor

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

        extra = {}
        if self.actor is not None:
            from police.workflow import available_transitions

            approval = getattr(complaint, "magistrate_approval", None)
            extra = {
                "version": complaint.version,
                "is_cognizable": complaint.is_cognizable,
                "available_transitions": available_transitions(complaint, self.actor),
                "magistrate_approval": {
                    "awaiting": approval.awaiting_approval,
                    "approved": approval.approved,
                    "comments": approval.comments,
                } if approval else None,
                "escalations": [
                    {
                        "to_role": item.escalated_to_role,
                        "reason": item.reason,
                        "created_at": item.created_at.isoformat(),
                    }
                    for item in complaint.escalations.all()
                ],
                "drafts": [
                    {
                        "draft_id": str(item.draft_id),
                        "document_type": item.document_type,
                        "version": item.version,
                        "status": item.status,
                        "source": item.source,
                    }
                    for item in complaint.fir_drafts.all()
                ],
            }

        return {
            **extra,
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
