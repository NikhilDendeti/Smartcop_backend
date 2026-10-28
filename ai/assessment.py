"""Runs the AI analysis of a filed complaint in the background and records the outcome."""

import logging

from django.db import transaction

from ai.classification import classify_incident
from ai.guards import safety_floor
from ai.services import finish_assessment
from users.consent import has_consent
from users.models import AIAssessment

logger = logging.getLogger(__name__)


def run_assessment(complaint_id):
    """Analyse one complaint. Safe to run twice: the second run finds nothing pending and stops."""
    assessment = (
        AIAssessment.objects.select_related("complaint", "complaint__user")
        .filter(complaint_id=complaint_id, ai_status="pending")
        .first()
    )
    if assessment is None:
        return "nothing_to_do"
    complaint = assessment.complaint

    if not has_consent(complaint.user):
        floor, _ = safety_floor(complaint.incident_summary)
        skipped = AIAssessment.objects.filter(pk=assessment.pk, ai_status="pending").update(
            ai_status="skipped",
            needs_review=True,
            urgency_score=floor if complaint.is_cognizable else 0,
            review_reasons=["The citizen has not agreed to AI-assisted analysis; an officer must triage this."],
        )
        if skipped and floor and complaint.is_cognizable:
            complaint.ai_urgency_score = floor
            complaint.save(update_fields=["ai_urgency_score", "updated_at"])
        return "skipped"

    result = classify_incident(complaint.incident_summary, complaint.incident_date, complaint=complaint)
    # A general-diary entry carries no urgency; a normal complaint takes the AI/floor score.
    urgency_override = None if complaint.is_cognizable else 0

    with transaction.atomic():
        if not finish_assessment(assessment, result, urgency_override=urgency_override):
            return "already_done"
        if complaint.is_cognizable:
            complaint.ai_urgency_score = result.urgency_score or 0
            complaint.save(update_fields=["ai_urgency_score", "updated_at"])
    return result.status


def enqueue_assessment(complaint_id):
    """Queue the analysis. If the queue is unreachable the assessment simply stays pending, and the
    reassess_pending command picks it up later; filing the complaint never fails because of it."""
    from ai.tasks import assess_complaint

    try:
        assess_complaint.delay(str(complaint_id))
    except Exception:
        logger.exception("Could not queue the AI analysis for complaint %s", complaint_id)
