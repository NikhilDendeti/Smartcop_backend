"""Case actions beyond a plain status change: assignment, escalation, magistrate approval,
investigation notes and FIR/GD drafts. Each one is a single transaction and goes through the
workflow rules, so none can leave a case half-updated or skip a required step."""

from django.db import transaction
from django.db.models import Max
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from police import workflow
from police.interactors.assign_complaint_to_hc import AssignComplaintToHCInteractor
from police.models import Escalation, FIRDraft, InvestigationUpdate, MagistrateApproval
from users import notify
from users.access import HEAD_CONSTABLE, SHO, SUB_INSPECTOR, actor_role
from users.models import Complaint

# Who may escalate to whom.
ESCALATION_TARGETS = {
    HEAD_CONSTABLE: (SUB_INSPECTOR, SHO),
    SUB_INSPECTOR: (SHO,),
}


def assign_complaint(complaint, actor, hc_phone, notes="", expected_version=None):
    with transaction.atomic():
        # The status change runs first so a complaint that cannot be assigned is rejected before
        # any assignment record is written.
        updated = workflow.apply_transition(
            complaint, "assigned", actor, remarks=notes, expected_version=expected_version
        )
        try:
            result = AssignComplaintToHCInteractor(
                complaint_id=complaint.pk, hc_phone=hc_phone, notes=notes, actor=actor
            ).execute()
        except ValueError as error:
            raise ValidationError(str(error))

        head_constable = updated.officer_assigned or Complaint.objects.get(pk=complaint.pk).officer_assigned
        if head_constable:
            notify.notify(head_constable, "case_assigned", "A complaint has been assigned to you.", updated)
    return result


def escalate(complaint, actor, to_role, reason):
    role = actor_role(actor)
    allowed = ESCALATION_TARGETS.get(role)
    if not allowed:
        raise PermissionDenied("Your role cannot escalate a complaint.")
    if to_role not in allowed:
        raise ValidationError({"to_role": f"You can escalate to: {', '.join(allowed)}."})
    if complaint.status == "resolved":
        raise workflow.InvalidTransition("A resolved complaint cannot be escalated.")

    with transaction.atomic():
        escalation = Escalation.objects.create(
            complaint=complaint, escalated_by=actor, escalated_to_role=to_role, reason=reason
        )
        notify.notify_officers(
            (to_role,), complaint.station, "case_escalated", "A complaint has been escalated to you.", complaint
        )
    return escalation


def request_magistrate_approval(complaint, actor, comments=""):
    with transaction.atomic():
        updated = workflow.apply_transition(complaint, "awaiting_magistrate", actor, remarks=comments)
        MagistrateApproval.objects.update_or_create(
            complaint=updated,
            defaults={
                "marked_by": actor,
                "awaiting_approval": True,
                "approved": False,
                "approval_date": None,
                "comments": comments,
            },
        )
        notify.notify_magistrates(
            "approval_requested", "A non-cognizable complaint is waiting for your decision.", updated
        )
    return updated


def decide_magistrate_approval(complaint, magistrate, approve, comments=""):
    with transaction.atomic():
        locked = Complaint.objects.select_for_update().get(pk=complaint.pk)
        if locked.status != "awaiting_magistrate":
            raise workflow.InvalidTransition("This complaint is not waiting for a magistrate's decision.")

        approval = locked.magistrate_approval
        approval.awaiting_approval = False
        approval.approved = approve
        approval.approval_date = timezone.localdate()
        approval.comments = comments
        approval.save()

        if approve:
            updated = workflow.apply_transition(
                locked, "under_investigation", magistrate, remarks=comments or "Approved by magistrate", system=True
            )
        else:
            updated = workflow.apply_transition(
                locked, "resolved", magistrate, remarks=comments or "Rejected by magistrate", system=True
            )
        notify.notify_officers(
            (SUB_INSPECTOR, SHO),
            updated.station,
            "magistrate_decision",
            "The magistrate has " + ("approved" if approve else "rejected") + " a complaint.",
            updated,
        )
    return updated


def add_note(complaint, actor, text):
    return InvestigationUpdate.objects.create(
        complaint=complaint, updated_by=actor, status=complaint.status, notes=text
    )


def create_draft(complaint, actor, document_type, content):
    if document_type == "fir":
        problem = workflow._investigation_allowed(complaint, "")
        if problem:
            raise workflow.InvalidTransition(problem)

    with transaction.atomic():
        Complaint.objects.select_for_update().get(pk=complaint.pk)
        latest = complaint.fir_drafts.filter(document_type=document_type).aggregate(latest=Max("version"))["latest"]
        return FIRDraft.objects.create(
            complaint=complaint,
            document_type=document_type,
            version=(latest or 0) + 1,
            content=content,
            source="officer",
            created_by=actor,
        )


def approve_draft(draft, actor):
    if draft.status != "draft":
        raise workflow.InvalidTransition(f"This draft is already {draft.status}.")
    draft.status = "approved"
    draft.approved_by = actor
    draft.approved_at = timezone.now()
    draft.save(update_fields=["status", "approved_by", "approved_at"])
    return draft
