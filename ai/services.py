from ai.models import AIRun
from users.models import AIAssessment


def save_assessment(complaint, result, *, urgency_override=None):
    """Store a ClassificationResult against a complaint and link the model calls that produced it."""
    sections = result.section_map
    model_label = f"{result.provider}:{result.model}"[:50] if result.provider else "unavailable"
    last_run = AIRun.objects.filter(pk__in=result.run_ids).order_by("-created_at").first()
    urgency = (result.urgency_score or 0) if urgency_override is None else urgency_override

    assessment = AIAssessment.objects.create(
        complaint=complaint,
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
        ai_run=last_run,
    )
    AIRun.objects.filter(pk__in=result.run_ids).update(complaint=complaint)
    return assessment
