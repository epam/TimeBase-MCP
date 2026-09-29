from __future__ import annotations

import json
from functools import lru_cache
from importlib import resources
from typing import Literal, Protocol, cast

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from timebase_mcp.errors import ConfigurationError
from timebase_mcp.models.logs_kb import FixConfidence

_RUNTIME_SCHEMA_VERSION = 1


class RuntimeEntry(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    runtime_schema_version: Literal[1]
    id: str
    symptom_signature: str
    symptom_summary: str
    log_excerpt: str | None = None
    root_cause: str
    suggested_action: str
    fix_version: str | None = None
    fix_confidence: FixConfidence
    tags: tuple[str, ...]
    search_text: str | None = None

    @field_validator(
        "id",
        "symptom_signature",
        "symptom_summary",
        "root_cause",
        "suggested_action",
        mode="before",
    )
    @classmethod
    def _normalize_required_text(cls, value: object) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("must be a non-empty string")
        return value.strip()

    @field_validator("log_excerpt", "fix_version", "search_text", mode="before")
    @classmethod
    def _normalize_optional_text(cls, value: object) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str) or not value.strip():
            raise ValueError("must be null or a non-empty string")
        return value.strip()

    @field_validator("tags", mode="before")
    @classmethod
    def _normalize_tags(cls, value: object) -> tuple[str, ...]:
        if not isinstance(value, (list, tuple)):
            raise TypeError("must be a list")

        tags: list[str] = []
        for item in value:
            if not isinstance(item, str) or not item.strip():
                raise ValueError("must contain non-empty strings")
            tags.append(item.strip())
        return tuple(tags)


class _ResourceArtifact(Protocol):
    def read_text(self, encoding: str = "utf-8") -> str: ...


class _ResourcePackage(Protocol):
    def joinpath(self, name: str) -> _ResourceArtifact: ...


def clear_runtime_entry_cache() -> None:
    load_runtime_entries.cache_clear()


@lru_cache(maxsize=1)
def load_runtime_entries() -> tuple[RuntimeEntry, ...]:
    try:
        package = cast(
            _ResourcePackage, resources.files("timebase_mcp.services.logs_kb.data")
        )
        artifact = package.joinpath("runtime_entries.jsonl")
    except ModuleNotFoundError as exc:
        raise ConfigurationError(
            "Bundled logs KB runtime artifact is not available."
        ) from exc

    try:
        text = artifact.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ConfigurationError(
            "Bundled logs KB runtime artifact is not available."
        ) from exc
    except OSError as exc:
        raise ConfigurationError(
            "Bundled logs KB runtime artifact could not be read."
        ) from exc

    entries: list[RuntimeEntry] = []
    for line_no, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue

        try:
            decoded = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ConfigurationError(
                f"Bundled logs KB runtime artifact is invalid: JSON error on line {line_no}."
            ) from exc

        if not isinstance(decoded, dict):
            raise ConfigurationError(
                f"Bundled logs KB runtime artifact is invalid: line {line_no} is not a JSON object."
            )

        entries.append(_validate_runtime_record(decoded, line_no))

    return tuple(entries)


def _validate_runtime_record(record: dict[str, object], line_no: int) -> RuntimeEntry:
    try:
        return RuntimeEntry.model_validate(record)
    except ValidationError as exc:
        if _has_schema_version_error(exc):
            raise ConfigurationError(
                "Bundled logs KB runtime artifact uses an unsupported schema version."
            ) from exc
        raise ConfigurationError(
            f"Bundled logs KB runtime artifact is invalid: line {line_no} {_format_validation_error(exc)}."
        ) from exc


def _has_schema_version_error(exc: ValidationError) -> bool:
    for error in exc.errors():
        if error.get("loc") == ("runtime_schema_version",):
            return True
    return False


def _format_validation_error(exc: ValidationError) -> str:
    first_error = exc.errors()[0]
    location = first_error.get("loc")
    if isinstance(location, tuple) and location:
        return f"field {location[0]!r} {first_error['msg']}"
    return str(first_error["msg"])
