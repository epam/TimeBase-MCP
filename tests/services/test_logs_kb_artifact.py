from __future__ import annotations

import json

import pytest

from timebase_mcp.errors import ConfigurationError
from timebase_mcp.services.logs_kb import artifact as logs_kb_artifact
from timebase_mcp.services.logs_kb.artifact import RuntimeEntry


@pytest.fixture(autouse=True)
def clear_runtime_entry_cache() -> None:
    logs_kb_artifact.clear_runtime_entry_cache()


def test_load_runtime_entries_returns_typed_entries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakeArtifact:
        def read_text(self, encoding: str = "utf-8") -> str:
            _ = encoding
            return json.dumps(
                {
                    "runtime_schema_version": 1,
                    "id": "block-empty",
                    "symptom_signature": "java.lang.IllegalStateException at deltix.Reader.read",
                    "symptom_summary": "A read fails with IllegalStateException while scanning stream data.",
                    "log_excerpt": "java.lang.IllegalStateException: Block is empty",
                    "root_cause": "The stream contains an empty or incomplete data block.",
                    "suggested_action": "Check the affected stream for damaged data and restore it from backup if needed.",
                    "fix_version": "5.7.16",
                    "fix_confidence": "likely",
                    "tags": ["storage", "cursor"],
                    "search_text": "block-empty summary excerpt cause action",
                }
            )

    class _FakePackage:
        def joinpath(self, name: str) -> _FakeArtifact:
            assert name == "runtime_entries.jsonl"
            return _FakeArtifact()

    monkeypatch.setattr(logs_kb_artifact.resources, "files", lambda _: _FakePackage())

    entries = logs_kb_artifact.load_runtime_entries()

    assert entries == (
        RuntimeEntry(
            runtime_schema_version=1,
            id="block-empty",
            symptom_signature="java.lang.IllegalStateException at deltix.Reader.read",
            symptom_summary="A read fails with IllegalStateException while scanning stream data.",
            log_excerpt="java.lang.IllegalStateException: Block is empty",
            root_cause="The stream contains an empty or incomplete data block.",
            suggested_action="Check the affected stream for damaged data and restore it from backup if needed.",
            fix_version="5.7.16",
            fix_confidence="likely",
            tags=("storage", "cursor"),
            search_text="block-empty summary excerpt cause action",
        ),
    )


def test_load_runtime_entries_rejects_unsupported_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakeArtifact:
        def read_text(self, encoding: str = "utf-8") -> str:
            _ = encoding
            return json.dumps(
                {
                    "runtime_schema_version": 999,
                    "id": "broken",
                    "symptom_signature": "sig",
                    "symptom_summary": "summary",
                    "log_excerpt": None,
                    "root_cause": "cause",
                    "suggested_action": "action",
                    "fix_version": None,
                    "fix_confidence": "unknown",
                    "tags": [],
                }
            )

    class _FakePackage:
        def joinpath(self, name: str) -> _FakeArtifact:
            assert name == "runtime_entries.jsonl"
            return _FakeArtifact()

    monkeypatch.setattr(logs_kb_artifact.resources, "files", lambda _: _FakePackage())

    with pytest.raises(ConfigurationError, match="unsupported schema version"):
        logs_kb_artifact.load_runtime_entries()


def test_load_runtime_entries_rejects_invalid_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakeArtifact:
        def read_text(self, encoding: str = "utf-8") -> str:
            _ = encoding
            return "{not-json}"

    class _FakePackage:
        def joinpath(self, name: str) -> _FakeArtifact:
            assert name == "runtime_entries.jsonl"
            return _FakeArtifact()

    monkeypatch.setattr(logs_kb_artifact.resources, "files", lambda _: _FakePackage())

    with pytest.raises(ConfigurationError, match="JSON error on line 1"):
        logs_kb_artifact.load_runtime_entries()


def test_load_runtime_entries_rejects_invalid_fix_confidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakeArtifact:
        def read_text(self, encoding: str = "utf-8") -> str:
            _ = encoding
            return json.dumps(
                {
                    "runtime_schema_version": 1,
                    "id": "broken",
                    "symptom_signature": "sig",
                    "symptom_summary": "summary",
                    "log_excerpt": None,
                    "root_cause": "cause",
                    "suggested_action": "action",
                    "fix_version": None,
                    "fix_confidence": "maybe",
                    "tags": [],
                    "search_text": "sig summary",
                }
            )

    class _FakePackage:
        def joinpath(self, name: str) -> _FakeArtifact:
            assert name == "runtime_entries.jsonl"
            return _FakeArtifact()

    monkeypatch.setattr(logs_kb_artifact.resources, "files", lambda _: _FakePackage())

    with pytest.raises(ConfigurationError, match="field 'fix_confidence'"):
        logs_kb_artifact.load_runtime_entries()
