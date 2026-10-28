"""Input and output safeguards around the model.

The model only suggests. These rules make sure a bad suggestion, an outage, or a hostile
complaint text can never quietly lower the priority of a serious case."""

import re
from datetime import date

from core.logging import redact_pii

MAX_INCIDENT_CHARS = 5000
CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
INCIDENT_TAG = re.compile(r"</?\s*incident\s*>", re.IGNORECASE)

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


def safety_floor(text: str):
    """Returns (minimum urgency, reasons) for text that mentions a serious offence."""
    floor = 0
    reasons = []
    for pattern, urgency, reason in SERIOUS_PATTERNS:
        if pattern.search(text):
            floor = max(floor, urgency)
            reasons.append(reason)
    return floor, reasons
