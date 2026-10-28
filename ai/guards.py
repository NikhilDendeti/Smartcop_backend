"""Input and output safeguards around the model.

The model only suggests. These rules make sure a bad suggestion, an outage, or a hostile
complaint text can never quietly lower the priority of a serious case."""

import re
from datetime import date

from core.logging import redact_pii

MAX_INCIDENT_CHARS = 5000
CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
# Every delimiter our prompts use to fence off citizen text. None may appear inside that text.
INCIDENT_TAG = re.compile(r"</?\s*(?:incident|conversation|case_data|case_status|question)\s*>", re.IGNORECASE)

# Coarse English keyword floor for the offences that must never be treated as routine. It raises
# urgency and forces officer review; it never lowers anything. Other languages are covered by the
# model and, later, by the evaluation set.
SERIOUS_PATTERNS = [
    (re.compile(r"\b(murder\w*|kill(?:ed|ing)?|stabb\w+|shot dead|beaten to death|died)\b", re.I), 90, "possible death or killing"),
    (re.compile(r"\b(rape\w*|raped|sexual(?:ly)? assault\w*|molest\w*|gang[- ]?rape)\b", re.I), 90, "possible sexual offence"),
    (re.compile(r"\b(kidnap\w*|abduct\w*|hostage)\b", re.I), 85, "possible kidnapping"),
    (re.compile(r"\b(acid attack|acid thrown|set (?:her|him|them) on fire|burn(?:t|ed) alive)\b", re.I), 90, "possible grievous violence"),
    (re.compile(r"\b(child|minor|underage)\b.{0,60}\b(abuse\w*|assault\w*|molest\w*|rape\w*|trafficking)\b", re.I | re.S), 90, "possible offence against a child"),
    (re.compile(r"\b(attempt(?:ed)? to (?:kill|murder)|tried to kill|life[- ]threatening)\b", re.I), 85, "possible attempt on life"),
]


def sanitize_incident(text: str) -> str:
    """Make complaint text safe to hand to a model: drop control characters, defuse our own
    delimiters so the text cannot close the data block, mask personal identifiers, cap length."""
    cleaned = CONTROL_CHARS.sub("", text or "")
    cleaned = INCIDENT_TAG.sub("[tag removed]", cleaned)
    cleaned = redact_pii(cleaned).strip()
    return cleaned[:MAX_INCIDENT_CHARS]


def wrap_incident(text: str, incident_date: date | None = None) -> str:
    context = f"Date of incident: {incident_date.isoformat()}\n" if incident_date else ""
    return f"{context}<incident>\n{text}\n</incident>"


EMERGENCY_NOTICE = (
    "If you or someone else is in danger right now, call 112 (emergency) immediately. "
    "Women's helpline: 1091. Child helpline: 1098."
)

# Phrases a citizen-facing reply must not contain: legal advice and outcome promises. This is a
# backstop to the prompt, not a complete defence.
FORBIDDEN_REPLY = re.compile(
    r"\b(you (?:will|are going to|should) (?:be )?(?:win|convict\w*|sue|plead|arrest\w*)|"
    r"(?:he|she|they|the accused) (?:will|is going to) (?:be )?(?:convict\w*|jail\w*|arrest\w*)|"
    r"guarantee\w*|i promise|legal advice)\b",
    re.I,
)
EMERGENCY_PATTERNS = re.compile(
    r"\b(in danger|right now|happening now|being (?:attacked|followed|beaten|threatened)|"
    r"he is (?:here|outside)|she is (?:here|outside)|bleeding|unconscious|help me)\b",
    re.I,
)


def looks_like_emergency(text: str) -> bool:
    """Rule-based emergency check, independent of the model, so help is shown even if the AI is down."""
    urgent_words = re.search(r"\b(in danger|help me|being attacked|bleeding|unconscious)\b", text, re.I)
    serious_and_ongoing = safety_floor(text)[0] >= 85 and EMERGENCY_PATTERNS.search(text)
    return bool(urgent_words or serious_and_ongoing)


def reply_is_safe(reply: str) -> bool:
    return not FORBIDDEN_REPLY.search(reply)


def safety_floor(text: str):
    """Returns (minimum urgency, reasons) for text that mentions a serious offence."""
    floor = 0
    reasons = []
    for pattern, urgency, reason in SERIOUS_PATTERNS:
        if pattern.search(text):
            floor = max(floor, urgency)
            reasons.append(reason)
    return floor, reasons
