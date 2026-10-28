"""How far along a complaint is, in words and as a percentage, for progress bars and timelines."""

from users.models import CASE_STATUSES

STATUS_LABELS = dict(CASE_STATUSES)

# A rough guide for the citizen, not a promise: every status has a value.
PROGRESS_PERCENT = {
    "pending": 10,
    "under_review": 25,
    "gd_recorded": 30,
    "assigned": 40,
    "awaiting_magistrate": 50,
    "under_investigation": 60,
    "fir_registered": 80,
    "resolved": 100,
}


def status_fields(status):
    return {"status_label": STATUS_LABELS.get(status, status), "progress_percent": PROGRESS_PERCENT.get(status, 0)}


def timeline(complaint):
    """What happened and when, for the citizen. Officers' remarks are internal and left out."""
    return [
        {"status": item.stage, "label": STATUS_LABELS.get(item.stage, item.stage), "at": item.timestamp.isoformat()}
        for item in complaint.progress_updates.all()
    ]


HIGH_URGENCY = 80
MEDIUM_URGENCY = 50


def priority_for(urgency_score):
    """The label shown on officer screens: high from 80, medium from 50, otherwise low."""
    score = urgency_score or 0
    if score >= HIGH_URGENCY:
        return "high"
    return "medium" if score >= MEDIUM_URGENCY else "low"
