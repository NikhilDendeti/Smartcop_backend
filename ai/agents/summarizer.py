"""Condenses a complaint file for the officer handling it. Every fact must cite the line of the
record it came from, and facts citing a line that does not exist are discarded."""

import re

from ai import gateway
from ai.agents.common import AssistantUnavailable, ask_model
from ai.guards import sanitize_incident
from ai.schemas import SUMMARY_SCHEMA, SUMMARY_SCHEMA_NAME, parse_summary
from users.consent import require_consent

SOURCE_ID = re.compile(r"^S\d+$")


def _sources(complaint):
    """Numbered source lines: {'S1': 'description', ...}."""
    entries = [
        ("Complainant's account", complaint.incident_summary),
        ("Place of incident", complaint.location),
    ]
    entries += [(f"Accused {i}", f"{a.name or 'unknown'}: {a.statement or a.description or ''}")
                for i, a in enumerate(complaint.accused.all(), start=1)]
    entries += [(f"Witness {i}", f"{w.name}: {w.statement or ''}")
                for i, w in enumerate(complaint.witnesses.all(), start=1)]
    entries += [(f"Officer note {i}", n.notes)
                for i, n in enumerate(complaint.investigation_updates.order_by("updated_at"), start=1)]
    return {f"S{i}": (label, text) for i, (label, text) in enumerate(entries, start=1)}


def summarize_case(complaint):
    require_consent(complaint.user)
    sources = _sources(complaint)
    record = "<case_data>\n" + "\n".join(
        f"[{key}] {label}: {sanitize_incident(text)}" for key, (label, text) in sources.items()
    ) + "\n</case_data>"

    def validate(data):
        parsed = parse_summary(data)
        for fact in parsed.facts:
            if not SOURCE_ID.match(fact.source) or fact.source not in sources:
                raise ValueError(f"fact cites an unknown source '{fact.source}'")
        return parsed

    try:
        outcome = ask_model("summarize", record, SUMMARY_SCHEMA, SUMMARY_SCHEMA_NAME, validate, complaint=complaint)
    except gateway.AIUnavailable:
        raise AssistantUnavailable("The summary assistant is unavailable. Please read the case file directly.") from None

    parsed = outcome.parsed
    return {
        "summary": parsed.summary,
        "facts": [
            {"text": fact.text, "source": fact.source, "source_label": sources[fact.source][0]}
            for fact in parsed.facts
        ],
        "open_questions": parsed.open_questions,
        "disclaimer": "AI-generated summary. Check it against the case file.",
    }
