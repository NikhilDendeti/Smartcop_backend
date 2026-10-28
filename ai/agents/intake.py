"""Complaint intake assistant: a short chat that helps a citizen describe an incident.

It only collects and structures what the citizen says. It does not file anything: when it has
enough, the citizen gets a pre-filled report to review, edit and submit themselves."""

import logging
from dataclasses import dataclass, field

from rest_framework.exceptions import ValidationError

from ai import gateway
from ai.agents.common import ask_model
from ai.guards import EMERGENCY_NOTICE, looks_like_emergency, reply_is_safe, sanitize_incident
from ai.schemas import INTAKE_SCHEMA, INTAKE_SCHEMA_NAME, parse_intake
from users.models import Conversation, Message

logger = logging.getLogger(__name__)

MAX_MESSAGES = 40
MAX_USER_MESSAGE_CHARS = 2000
HISTORY_WINDOW = 20

DISCLOSURE = (
    "This assistant uses AI to help you describe what happened. It is not a lawyer or a police officer "
    "and cannot give legal advice. You will review everything before anything is sent to the police."
)
UNAVAILABLE_REPLY = (
    "The assistant is not available right now. You can describe what happened directly in the "
    "complaint form instead."
)
UNSAFE_REPLY = "Could you tell me a little more about what happened, where, and when?"


@dataclass
class IntakeResult:
    reply: str
    emergency: bool
    ready: bool
    missing: list = field(default_factory=list)
    report: dict = field(default_factory=dict)
    ai_available: bool = True


def _transcript(conversation):
    recent = list(conversation.messages.order_by("-created_at")[:HISTORY_WINDOW])[::-1]
    lines = []
    for message in recent:
        speaker = "Citizen" if message.role == "user" else "Assistant"
        lines.append(f"{speaker}: {sanitize_incident(message.content)}")
    return "<conversation>\n" + "\n".join(lines) + "\n</conversation>"


def start(user, language="en"):
    return Conversation.objects.create(user=user, kind="intake", language=language[:50])


def send_message(conversation, content) -> IntakeResult:
    if conversation.status != "open":
        raise ValidationError("This conversation is closed.")
    if len(content) > MAX_USER_MESSAGE_CHARS:
        raise ValidationError({"content": f"Keep each message under {MAX_USER_MESSAGE_CHARS} characters."})
    if conversation.messages.count() >= MAX_MESSAGES:
        raise ValidationError("This conversation is too long. Please continue in the complaint form.")

    Message.objects.create(conversation=conversation, role="user", content=content)
    emergency = looks_like_emergency(content)

    try:
        outcome = ask_model("intake", _transcript(conversation), INTAKE_SCHEMA, INTAKE_SCHEMA_NAME, parse_intake)
    except gateway.AIUnavailable:
        reply = UNAVAILABLE_REPLY + (f"\n\n{EMERGENCY_NOTICE}" if emergency else "")
        Message.objects.create(conversation=conversation, role="assistant", content=reply)
        return IntakeResult(reply=reply, emergency=emergency, ready=False, ai_available=False)

    turn = outcome.parsed
    emergency = emergency or turn.emergency
    reply = turn.reply
    if not reply_is_safe(reply):
        logger.warning("Intake reply blocked by the safety check")
        reply = UNSAFE_REPLY
    if emergency:
        # Appended by code, not the model, so the safety information is always exact.
        reply = f"{reply}\n\n{EMERGENCY_NOTICE}"

    report = turn.report.model_dump()
    Message.objects.create(
        conversation=conversation,
        role="assistant",
        content=reply,
        data={"ready": turn.ready, "missing": turn.missing, "report": report, "emergency": emergency},
        ai_run_id=outcome.run_ids[-1] if outcome.run_ids else None,
    )
    return IntakeResult(reply=reply, emergency=emergency, ready=turn.ready, missing=turn.missing, report=report)


def prefill(conversation):
    """The latest report the assistant built, for the citizen to review. Empty until it is ready."""
    for message in conversation.messages.filter(role="assistant").order_by("-created_at"):
        if message.data.get("ready"):
            return message.data["report"]
    return None
