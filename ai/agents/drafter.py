"""Drafts the narrative of an FIR or General Diary entry for an officer to edit.

The result is stored as a draft marked as AI-written. It cannot count as approved until a
commanding officer approves it, and it cannot register an FIR by itself."""

from rest_framework.exceptions import PermissionDenied

from ai import gateway
from ai.agents.common import AssistantUnavailable, ask_model
from ai.guards import sanitize_incident
from ai.schemas import DRAFT_SCHEMA, DRAFT_SCHEMA_NAME, parse_draft
from police import cases
from users.consent import require_consent

DOCUMENT_NAMES = {"fir": "First Information Report (FIR)", "gd": "General Diary (GD) entry"}
WATERMARK = "[AI-generated draft. Check every fact against the record before approving.]\n\n"


def _record(complaint):
    """The case file as text for the model. Phone numbers, emails and Aadhar numbers are masked;
    names stay because a report cannot be drafted without them."""
    lines = [
        f"Complaint type: {complaint.case_type.get_name_display()}",
        f"Date of incident: {complaint.incident_date}",
        f"Time of incident: {complaint.incident_time}",
        f"Place of incident: {sanitize_incident(complaint.location)}",
        f"Complainant's account: {sanitize_incident(complaint.incident_summary)}",
    ]
    assessment = getattr(complaint, "assessment", None)
    if assessment and assessment.ipc_sections:
        status = "confirmed by an officer" if assessment.reviewed_at else "suggested by AI, not yet confirmed"
        listed = "; ".join(f"{code} {title}" for code, title in assessment.ipc_sections.items())
        lines.append(f"Possibly applicable sections ({status}): {listed}")
    for index, accused in enumerate(complaint.accused.all(), start=1):
        lines.append(
            f"Accused {index}: name {accused.name or 'unknown'}; description "
            f"{sanitize_incident(accused.description or 'none')}; statement {sanitize_incident(accused.statement or 'none')}"
        )
    for index, witness in enumerate(complaint.witnesses.all(), start=1):
        lines.append(f"Witness {index}: name {witness.name}; statement {sanitize_incident(witness.statement or 'none')}")
    return "<case_data>\n" + "\n".join(lines) + "\n</case_data>"


def draft_document(complaint, actor, document_type):
    require_consent(complaint.user)
    if document_type not in DOCUMENT_NAMES:
        raise PermissionDenied("Unknown document type.")

    try:
        outcome = ask_model(
            "draft",
            _record(complaint),
            DRAFT_SCHEMA,
            DRAFT_SCHEMA_NAME,
            parse_draft,
            complaint=complaint,
            document_name=DOCUMENT_NAMES[document_type],
        )
    except gateway.AIUnavailable:
        raise AssistantUnavailable("The drafting assistant is unavailable. Please write the draft manually.") from None

    return cases.create_draft(
        complaint,
        actor,
        document_type,
        WATERMARK + outcome.parsed.content,
        source="ai",
        ai_run_id=outcome.run_ids[-1] if outcome.run_ids else None,
    )
