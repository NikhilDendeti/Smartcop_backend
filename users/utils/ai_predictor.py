"""Compatibility wrapper. The real work lives in the ai app (provider choice, fallback, validation).

This keeps the old function name and result keys so existing callers continue to work."""

from ai.classification import classify_incident


def get_ai_assessment(incident_summary: str, incident_date=None):
    result = classify_incident(incident_summary, incident_date)

    response = {
        "ai_status": result.status,
        "needs_review": result.needs_review,
        "reasons": result.reasons,
        "act": result.act,
        "is_cognizable": result.is_cognizable,
        "ipc_sections": result.section_map,
    }
    if result.urgency_score is not None:
        response["AI_urgency_score"] = result.urgency_score
    if result.is_cognizable is False:
        response["message"] = "This is a non-cognizable offence. It will be recorded as a General Diary (GD) entry."
    return response
