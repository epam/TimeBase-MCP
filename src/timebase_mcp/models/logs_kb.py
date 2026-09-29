from typing import Literal

from pydantic import BaseModel, Field

FixConfidence = Literal["confirmed", "likely", "unknown"]


class LogsKBMatch(BaseModel):
    id: str
    symptom_signature: str
    symptom_summary: str
    root_cause: str
    suggested_action: str
    fix_version: str | None = None
    fix_confidence: FixConfidence
    tags: list[str] = Field(default_factory=list)


class SearchLogsKBResult(BaseModel):
    query: str
    normalized_query: str
    advice: list[str] = Field(default_factory=list)
    matches: list[LogsKBMatch] = Field(default_factory=list)
