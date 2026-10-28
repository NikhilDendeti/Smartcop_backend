"""Triage suggestions for a commanding officer: how urgent a complaint looks and who has room to
take it. This is plain rules over data we already hold; no model is involved, so it works when the
AI is down. It only suggests; the officer assigns."""

from ai.guards import safety_floor
from police.models import OfficerRole
from users.models import Complaint

OPEN_STATUSES = ("assigned", "under_investigation")


def suggest(complaint):
    assessment = getattr(complaint, "assessment", None)
    reasons = []
    scores = []

    if assessment and assessment.ai_status in ("ok", "needs_review") and assessment.urgency_score:
        scores.append(assessment.urgency_score)
        reasons.append(f"AI-suggested urgency {assessment.urgency_score}.")
    floor, floor_reasons = safety_floor(complaint.incident_summary)
    if floor:
        scores.append(floor)
        reasons += [f"The account mentions a {reason}." for reason in floor_reasons]
    if assessment and assessment.ai_status in ("pending", "unavailable", "skipped"):
        reasons.append("No AI assessment is available; urgency is based on the account text only.")
    if assessment and assessment.needs_review and assessment.reviewed_at is None:
        reasons.append("The AI result has not been reviewed by an officer yet.")

    roles = OfficerRole.objects.filter(
        designation="head_constable", station=complaint.station, is_active=True
    ).select_related("officer")
    assignees = sorted(
        (
            {
                "name": role.officer.name,
                "phone": role.officer.phone,
                "open_cases": Complaint.objects.filter(
                    officer_assigned=role.officer, status__in=OPEN_STATUSES
                ).count(),
            }
            for role in roles
        ),
        key=lambda item: (item["open_cases"], item["name"]),
    )

    return {
        "suggested_urgency": max(scores) if scores else None,
        "reasons": reasons,
        "suggested_assignees": assignees,
        "note": "Suggestions only. The assigning officer decides.",
    }
