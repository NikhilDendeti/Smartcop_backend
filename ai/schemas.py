import re

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Flat, strict JSON Schema shared by every provider. Written by hand because the vendors accept
# different subsets of JSON Schema; pydantic below enforces the stricter rules (ranges, formats).
CLASSIFY_SCHEMA_NAME = "report_sections"
CLASSIFY_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["sections"],
    "properties": {
        "sections": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["code", "title", "confidence"],
                "properties": {
                    "code": {"type": "string"},
                    "title": {"type": "string"},
                    "confidence": {"type": "number"},
                },
            },
        }
    },
}

SECTION_CODE = re.compile(r"^\d{1,4}[A-Za-z]{0,2}(\(\d{1,2}\))?(\([a-z]\))?$")
CODE_PREFIX = re.compile(r"^(?:ipc|bns|section|sec\.?|s\.)\s*", re.IGNORECASE)


class SectionOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    title: str = Field(max_length=300)
    confidence: float = Field(ge=0, le=1)

    @field_validator("code")
    @classmethod
    def normalise_code(cls, value):
        code = CODE_PREFIX.sub("", value.strip()).replace(" ", "")
        if not SECTION_CODE.match(code):
            raise ValueError(f"'{value}' is not a section number")
        return code


class ClassificationOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sections: list[SectionOut] = Field(max_length=10)


def parse_classification(data: dict) -> ClassificationOut:
    return ClassificationOut.model_validate(data)


def _object(properties: dict) -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": list(properties),
        "properties": properties,
    }


STRING = {"type": "string"}
BOOLEAN = {"type": "boolean"}
STRING_LIST = {"type": "array", "items": STRING}

# --- Intake assistant -------------------------------------------------------------------------
CASE_TYPES = ("murder", "theft", "crime_against_women", "public_nuisance", "")

INTAKE_SCHEMA_NAME = "intake_turn"
INTAKE_SCHEMA = _object(
    {
        "reply": STRING,
        "emergency": BOOLEAN,
        "ready": BOOLEAN,
        "missing": STRING_LIST,
        "report": _object(
            {
                "incident_summary": STRING,
                "case_type": STRING,
                "location": STRING,
                "incident_date": STRING,
                "incident_time": STRING,
            }
        ),
    }
)


class IntakeReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    incident_summary: str = Field(max_length=5000)
    case_type: str
    location: str = Field(max_length=1000)
    incident_date: str
    incident_time: str

    @field_validator("case_type")
    @classmethod
    def known_case_type(cls, value):
        if value not in CASE_TYPES:
            raise ValueError("unknown case type")
        return value

    @field_validator("incident_date")
    @classmethod
    def iso_date(cls, value):
        if value and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise ValueError("date must be YYYY-MM-DD")
        return value

    @field_validator("incident_time")
    @classmethod
    def clock_time(cls, value):
        if value and not re.fullmatch(r"\d{2}:\d{2}(:\d{2})?", value):
            raise ValueError("time must be HH:MM")
        return value


class IntakeTurnOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reply: str = Field(min_length=1, max_length=2000)
    emergency: bool
    ready: bool
    missing: list[str] = Field(max_length=10)
    report: IntakeReport


def parse_intake(data: dict) -> IntakeTurnOut:
    return IntakeTurnOut.model_validate(data)


# --- Draft writer -----------------------------------------------------------------------------
DRAFT_SCHEMA_NAME = "write_draft"
DRAFT_SCHEMA = _object({"content": STRING})


class DraftOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1, max_length=20000)


def parse_draft(data: dict) -> DraftOut:
    return DraftOut.model_validate(data)


# --- Case summary -----------------------------------------------------------------------------
SUMMARY_SCHEMA_NAME = "summarise_case"
SUMMARY_SCHEMA = _object(
    {
        "summary": STRING,
        "facts": {"type": "array", "items": _object({"text": STRING, "source": STRING})},
        "open_questions": STRING_LIST,
    }
)


class FactOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(max_length=1000)
    source: str


class SummaryOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=1, max_length=3000)
    facts: list[FactOut] = Field(max_length=30)
    open_questions: list[str] = Field(max_length=15)


def parse_summary(data: dict) -> SummaryOut:
    return SummaryOut.model_validate(data)


# --- Citizen assistant ------------------------------------------------------------------------
ASSIST_SCHEMA_NAME = "answer_question"
ASSIST_SCHEMA = _object({"answer": STRING, "needs_human": BOOLEAN})


class AssistOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str = Field(min_length=1, max_length=1500)
    needs_human: bool


def parse_assist(data: dict) -> AssistOut:
    return AssistOut.model_validate(data)
