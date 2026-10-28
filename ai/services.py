from ai.models import AIRun
from users.models import AIAssessment


def create_pending_assessment(complaint):
    """A placeholder filed with the complaint, so it exists immediately and is visibly waiting for
    analysis rather than looking like it has no result."""
    return AIAssessment.objects.create(
        complaint=complaint,
        ipc_sections={},
        ipc_descriptions={},
        urgency_score=0,
        model_version="pending",
        ai_status="pending",
        needs_review=True,
        review_reasons=["Waiting for AI analysis."],
    )


def finish_assessment(assessment, result, *, urgency_override=None):
    """Store a ClassificationResult on a pending assessment. Returns False if another worker already
    finished it, so the same complaint is never analysed and overwritten twice."""
    sections = result.section_map
    model_label = f"{result.provider}:{result.model}"[:50] if result.provider else "unavailable"
    last_run = AIRun.objects.filter(pk__in=result.run_ids).order_by("-created_at").first()
    urgency = (result.urgency_score or 0) if urgency_override is None else urgency_override

    claimed = AIAssessment.objects.filter(pk=assessment.pk, ai_status="pending").update(
        ipc_sections=sections,
        ipc_descriptions=sections,
        urgency_score=urgency,
        model_version=model_label,
        provider=result.provider,
        model_name=result.model,
        prompt_version=result.prompt_version,
        confidence=result.confidence,
        needs_review=result.needs_review,
        ai_status=result.status,
        review_reasons=result.reasons,
        ai_run=last_run,
    )
    if claimed:
        AIRun.objects.filter(pk__in=result.run_ids).update(complaint=assessment.complaint)
    return bool(claimed)
