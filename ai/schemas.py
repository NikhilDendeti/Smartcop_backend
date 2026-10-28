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
