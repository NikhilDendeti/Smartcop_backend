from users.models import Complaint, AIAssessment, Accused, Witness, Evidence
from users.progress import status_fields, timeline
from django.core.exceptions import ObjectDoesNotExist

class GetComplaintDetailsInteractor:
    def __init__(self, complaint_id):
        self.complaint_id = complaint_id

    def get_complaint_details(self):
        try:
            complaint = Complaint.objects.select_related('user', 'case_type').get(complaint_id=self.complaint_id)

            assessment = getattr(complaint, 'assessment', None)
            accused_list = complaint.accused.all()
            witnesses_list = complaint.witnesses.all()
            evidence_list = complaint.evidence.all()

            return {
                "complaint_id": str(complaint.complaint_id),
                "user": {
                    "user_id": str(complaint.user.user_id),
                    "name": complaint.user.name,
                    "phone": complaint.user.phone,
                    "email": complaint.user.email,
                },
                "case_type": complaint.case_type.get_name_display(),
                "incident_summary": complaint.incident_summary,
                "location": complaint.location,
                "incident_date": str(complaint.incident_date),
                "incident_time": str(complaint.incident_time),
                "is_cognizable": complaint.is_cognizable,
                "status": complaint.status,
                **status_fields(complaint.status),
                "ai_status": assessment.ai_status if assessment else None,
                "timeline": timeline(complaint),
                "ai_urgency_score": complaint.ai_urgency_score,
                "created_at": str(complaint.created_at),
                "assessment": {
                    "ai_status": assessment.ai_status if assessment else None,
                    "ipc_sections": assessment.ipc_sections if assessment else {},
                    "ipc_descriptions": assessment.ipc_descriptions if assessment else {},
                    "urgency_score": assessment.urgency_score if assessment else None,
                    "model_version": assessment.model_version if assessment else None,
                    "generated_at": str(assessment.generated_at) if assessment else None,
                },
                "accused": [
                    {
                        "name": acc.name,
                        "description": acc.description,
                        "contact_info": acc.contact_info,
                        "statement": acc.statement
                    } for acc in accused_list
                ],
                "witnesses": [
                    {
                        "name": wit.name,
                        "contact_info": wit.contact_info,
                        "statement": wit.statement
                    } for wit in witnesses_list
                ],
                "evidence": [
                    {
                        "type": ev.type,
                        "file_url": ev.file_url,
                        "uploaded_at": str(ev.uploaded_at)
                    } for ev in evidence_list
                ],
                "evidence_files": [
                    {
                        "file_id": str(item.file_id),
                        "filename": item.original_filename,
                        "type": item.file_type,
                        "size_bytes": item.size_bytes,
                        "uploaded": item.verified_at is not None,
                        "scan_status": item.scan_status,
                    } for item in complaint.evidence_files.order_by('uploaded_at')
                ],
            }
        except ObjectDoesNotExist:
            return None
