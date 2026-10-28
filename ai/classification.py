"""Turns a citizen's incident text into suggested legal sections, urgency and a review flag.

Nothing here decides a case. The result is a suggestion with the reasons it may need an officer's
attention, and when the AI cannot answer the result says so instead of guessing."""

import datetime
from dataclasses import dataclass, field

from django.conf import settings

from ai import gateway
from ai.guards import safety_floor, sanitize_incident, wrap_incident
from ai.models import LegalSection
from ai.prompts import get_prompt, version_label
from ai.providers.base import LLMRequest
from ai.schemas import CLASSIFY_SCHEMA, CLASSIFY_SCHEMA_NAME, parse_classification

# The Indian Penal Code was replaced by the Bharatiya Nyaya Sanhita for offences on or after this date.
BNS_IN_FORCE = datetime.date(2024, 7, 1)
UNKNOWN_SECTION_URGENCY = 50

# What the product used before the legal table existed. Kept only as a flagged fallback until the
# table's cognizable flags are filled in by a legal reviewer.
LEGACY_COGNIZABLE_IPC = {"302", "376", "307", "354"}


def act_for(incident_date: datetime.date | None) -> str:
    when = incident_date or datetime.date.today()
    return "ipc" if when < BNS_IN_FORCE else "bns"


def parse_date(value):
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date) or value is None:
        return value
    try:
        return datetime.date.fromisoformat(str(value))
    except ValueError:
        return None


@dataclass
class SectionResult:
    code: str
    title: str
    confidence: float
    known: bool
    is_cognizable: bool | None
    urgency: int


@dataclass
class ClassificationResult:
    status: str  # "ok", "needs_review" or "unavailable"
    act: str
    sections: list = field(default_factory=list)
    is_cognizable: bool | None = None
    urgency_score: int | None = None
    needs_review: bool = True
    reasons: list = field(default_factory=list)
    confidence: float | None = None
    provider: str = ""
    model: str = ""
    prompt_version: str = ""
    run_ids: list = field(default_factory=list)

    @property
    def section_map(self):
        return {section.code: section.title for section in self.sections}


def _cognizable(sections, act, reasons):
    known_flags = [section.is_cognizable for section in sections if section.is_cognizable is not None]
    if known_flags and len(known_flags) == len(sections):
        return any(known_flags)

    if act == "ipc" and sections:
        reasons.append("Cognizable status is not confirmed in the legal table; the old rule was used.")
        return any(section.code in LEGACY_COGNIZABLE_IPC for section in sections)

    if sections:
        reasons.append("Cognizable status is not confirmed in the legal table.")
    return None


def classify_incident(summary, incident_date=None, *, complaint=None) -> ClassificationResult:
    incident_date = parse_date(incident_date)
    act = act_for(incident_date)
    text = sanitize_incident(summary)
    floor, floor_reasons = safety_floor(text)

    prompt, prompt_version = get_prompt("classify", act)
    request = LLMRequest(
        task="classify",
        system=prompt,
        user=wrap_incident(text, incident_date),
        schema=CLASSIFY_SCHEMA,
        schema_name=CLASSIFY_SCHEMA_NAME,
        max_tokens=settings.AI_MAX_OUTPUT_TOKENS,
    )

    try:
        outcome = gateway.run_structured(
            request, parse_classification, prompt_version=prompt_version, complaint=complaint
        )
    except gateway.AIUnavailable as unavailable:
        return ClassificationResult(
            status="unavailable",
            act=act,
            urgency_score=floor or None,
            needs_review=True,
            reasons=[f"AI unavailable ({unavailable.reason}); an officer must triage this."] + floor_reasons,
            prompt_version=version_label(prompt_version),
            run_ids=unavailable.run_ids,
        )

    reasons = list(floor_reasons)
    suggested = outcome.parsed.sections
    table = {
        section.code: section
        for section in LegalSection.objects.filter(act=act, code__in=[item.code for item in suggested])
    }

    sections = []
    for item in suggested:
        row = table.get(item.code)
        sections.append(
            SectionResult(
                code=item.code,
                title=item.title,
                confidence=item.confidence,
                known=row is not None,
                is_cognizable=row.is_cognizable if row else None,
                urgency=row.default_urgency if row else UNKNOWN_SECTION_URGENCY,
            )
        )

    needs_review = bool(floor_reasons)
    if not sections:
        reasons.append("No sections were suggested.")
        needs_review = True
    unknown = [section.code for section in sections if not section.known]
    if unknown:
        reasons.append(f"Sections not in the legal table: {', '.join(unknown)}.")
        needs_review = True
    low = [section.code for section in sections if section.confidence < settings.AI_MIN_CONFIDENCE]
    if low:
        reasons.append(f"Low confidence on: {', '.join(low)}.")
        needs_review = True

    is_cognizable = _cognizable(sections, act, reasons)
    cognizable_unconfirmed = any("not confirmed" in reason for reason in reasons)
    if cognizable_unconfirmed:
        needs_review = True

    urgency = max([section.urgency for section in sections] + [floor]) if (sections or floor) else None

    return ClassificationResult(
        status="needs_review" if needs_review else "ok",
        act=act,
        sections=sections,
        is_cognizable=is_cognizable,
        urgency_score=urgency,
        needs_review=needs_review,
        reasons=reasons,
        confidence=min((section.confidence for section in sections), default=None),
        provider=outcome.provider,
        model=outcome.model,
        prompt_version=version_label(prompt_version),
        run_ids=outcome.run_ids,
    )
