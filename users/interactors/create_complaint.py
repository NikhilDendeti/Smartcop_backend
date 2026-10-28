from django.db import transaction

from ai.assessment import enqueue_assessment
from ai.services import create_pending_assessment
from police.models import CaseProgress
from users.models import Complaint, Evidence, Accused, Witness, CaseType

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

        # Everything below is saved together or not at all. The AI analysis runs in the background
        # after the commit; until then the complaint carries a visible "pending" assessment, and if
        # the AI is down it is flagged for manual triage instead.
        with transaction.atomic():
            complaint = Complaint.objects.create(
                user=self.user,
                case_type=case_type_obj,
                is_cognizable=is_cognizable,
                incident_date=incident_date,
                incident_time=incident_time,
                location=location,
                incident_summary=incident_summary,
                station=self.data.get("station")
            )

            create_pending_assessment(complaint)
            CaseProgress.objects.create(
                complaint=complaint, stage=complaint.status, updated_by=self.user, remarks="Complaint registered"
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

            transaction.on_commit(lambda: enqueue_assessment(complaint.pk))

        return complaint
