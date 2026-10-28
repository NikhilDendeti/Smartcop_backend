"""Answers a citizen's questions about the status of their own complaint.

It can only see a small, fixed view of that one complaint (status and dates), never free-form
database access, and it falls back to a fixed status message whenever the AI cannot answer."""

from ai import gateway
from ai.agents.common import ask_model
from ai.guards import reply_is_safe, sanitize_incident
from ai.schemas import ASSIST_SCHEMA, ASSIST_SCHEMA_NAME, parse_assist
from police.models import CaseProgress
from users.consent import require_consent
from users.models import CASE_STATUSES, ChatQuery

LABELS = dict(CASE_STATUSES)
NEXT_STEPS = {
    "pending": "Your complaint has been received and is waiting to be reviewed by the police station.",
    "under_review": "An officer is reviewing your complaint.",
    "assigned": "Your complaint has been assigned to an officer who will look into it.",
    "under_investigation": "The police are investigating your complaint. You may be contacted for more information.",
    "awaiting_magistrate": "Your complaint is a non-cognizable matter. The police are waiting for a magistrate's permission before taking action.",
    "fir_registered": "An FIR has been registered on your complaint.",
    "gd_recorded": "Your complaint has been recorded in the General Diary. For a non-cognizable matter the police need a magistrate's permission before they can investigate.",
    "resolved": "Your complaint has been closed.",
}


def status_summary(complaint):
    return f"Status: {LABELS[complaint.status]}. {NEXT_STEPS[complaint.status]}"


def _case_status(complaint):
    history = CaseProgress.objects.filter(complaint=complaint).order_by("-timestamp")[:5]
    lines = [status_summary(complaint), f"Registered on: {complaint.created_at.date()}"]
    lines += [f"{LABELS.get(item.stage, item.stage)} on {item.timestamp.date()}" for item in history]
    return "\n".join(lines)


def answer_question(user, complaint, question):
    require_consent(user)
    clean_question = sanitize_incident(question)[:1000]
    data = f"<case_status>\n{_case_status(complaint)}\n</case_status>\n<question>\n{clean_question}\n</question>"

    answer, needs_human, ai_available = None, True, True
    try:
        outcome = ask_model("assist", data, ASSIST_SCHEMA, ASSIST_SCHEMA_NAME, parse_assist, complaint=complaint)
        answer, needs_human = outcome.parsed.answer, outcome.parsed.needs_human
        if not reply_is_safe(answer):
            answer = None
    except gateway.AIUnavailable:
        ai_available = False

    if answer is None:
        answer = status_summary(complaint) + " For anything else, please contact your police station."
        needs_human = True

    ChatQuery.objects.create(user=user, query_text=question[:2000], response_text=answer, language="auto", mode="text")
    return {"answer": answer, "needs_human": needs_human, "ai_available": ai_available}
