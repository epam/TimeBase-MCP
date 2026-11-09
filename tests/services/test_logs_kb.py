from __future__ import annotations

import subprocess
import sys

import pytest

from timebase_mcp.services.logs_kb import search as logs_kb_search
from timebase_mcp.services.logs_kb.artifact import RuntimeEntry


@pytest.fixture(autouse=True)
def clear_logs_kb_caches() -> None:
    logs_kb_search.clear_search_index_cache()


@pytest.fixture
def sample_runtime_entries() -> tuple[RuntimeEntry, ...]:
    return (
        RuntimeEntry(
            runtime_schema_version=1,
            id="block-empty",
            symptom_signature="java.lang.IllegalStateException at deltix.qsrv.hf.tickdb.impl.Reader.read",
            symptom_summary="A read fails with IllegalStateException while scanning stream data.",
            log_excerpt="java.lang.IllegalStateException: Block is empty\n\tat deltix.qsrv.hf.tickdb.impl.Reader.read(Reader.java:42)",
            root_cause="The stream contains an empty or incomplete data block.",
            suggested_action="Check the affected stream for damaged data and restore it from a known-good copy if needed.",
            fix_version="5.7.16",
            fix_confidence="likely",
            tags=("storage", "cursor"),
            search_text="storage cursor block empty repair stream 5.7.16",
        ),
        RuntimeEntry(
            runtime_schema_version=1,
            id="broad-startup",
            symptom_signature="java.lang.IllegalStateException",
            symptom_summary="A startup operation fails with a generic IllegalStateException.",
            log_excerpt="java.lang.IllegalStateException: startup failed",
            root_cause="The exact trigger is unclear from available evidence.",
            suggested_action="Capture the first stack frame and nearby error lines before triaging further.",
            fix_version=None,
            fix_confidence="unknown",
            tags=("startup",),
            search_text="startup failed illegal state",
        ),
    )


@pytest.mark.parametrize("query", ["", "   ", "\n\t"])
def test_search_logs_kb_rejects_empty_query(query: str) -> None:
    with pytest.raises(ValueError, match="query must be a non-empty string"):
        logs_kb_search.search_logs_kb(query)


def test_search_logs_kb_rejects_limit_below_one() -> None:
    with pytest.raises(ValueError, match="limit must be an integer >= 1"):
        logs_kb_search.search_logs_kb("java.lang.IllegalStateException", limit=0)


@pytest.mark.parametrize("character", ["a", "🙂"])
def test_search_entries_accepts_max_raw_query_characters(character: str) -> None:
    query = f" {character * 65_534} "

    result = logs_kb_search.search_entries((), query)

    assert result.query == character * 65_534
    assert result.normalized_query == character * 900


@pytest.mark.parametrize(
    "query",
    [
        pytest.param("x" * 65_537, id="text"),
        pytest.param(" " * 65_537, id="whitespace"),
        pytest.param(" " * 65_536 + "x", id="padding"),
    ],
)
def test_search_entries_rejects_oversized_raw_query_before_normalizing(
    monkeypatch: pytest.MonkeyPatch, query: str
) -> None:
    def fail_normalization(_query: str) -> str:
        pytest.fail("oversized queries must not be normalized")

    monkeypatch.setattr(logs_kb_search, "normalize_query_text", fail_normalization)

    with pytest.raises(
        ValueError, match="^query must contain at most 65536 characters$"
    ):
        logs_kb_search.search_entries((), query)


def test_search_logs_kb_rejects_oversized_raw_query_before_loading(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_loading() -> tuple[RuntimeEntry, ...]:
        pytest.fail("oversized queries must not load runtime entries")

    monkeypatch.setattr(logs_kb_search, "load_runtime_entries", fail_loading)

    with pytest.raises(
        ValueError, match="^query must contain at most 65536 characters$"
    ):
        logs_kb_search.search_logs_kb("x" * 65_537)


def test_search_entries_returns_best_match(
    sample_runtime_entries: tuple[RuntimeEntry, ...],
) -> None:
    result = logs_kb_search.search_entries(
        sample_runtime_entries,
        "java.lang.IllegalStateException: Block is empty\n\tat deltix.qsrv.hf.tickdb.impl.Reader.read(Reader.java:42)",
        limit=3,
    )

    assert result.query == (
        "java.lang.IllegalStateException: Block is empty\n\tat deltix.qsrv.hf.tickdb.impl.Reader.read(Reader.java:42)"
    )
    assert result.normalized_query == (
        "java.lang.IllegalStateException: Block is empty\nat deltix.qsrv.hf.tickdb.impl.Reader.read(Reader.java:42)"
    )
    assert result.advice == []
    assert [match.id for match in result.matches] == ["block-empty", "broad-startup"]
    assert result.matches[0].fix_version == "5.7.16"
    assert result.matches[0].fix_confidence == "likely"
    assert result.matches[0].tags == ["storage", "cursor"]


def test_search_entries_returns_advice_for_broad_query(
    sample_runtime_entries: tuple[RuntimeEntry, ...],
) -> None:
    result = logs_kb_search.search_entries(
        sample_runtime_entries,
        "java.lang.IllegalStateException: startup failed",
    )

    assert result.advice == [
        "query looks broad; add the first stack frame or adjacent error lines to improve precision"
    ]
    assert result.matches[0].id == "broad-startup"


def test_search_entries_returns_empty_matches_when_nothing_matches(
    sample_runtime_entries: tuple[RuntimeEntry, ...],
) -> None:
    result = logs_kb_search.search_entries(
        sample_runtime_entries,
        "completely unrelated failure text",
    )

    assert result.matches == []
    assert result.advice == []


def test_search_entries_normalizes_multiline_excerpt(
    sample_runtime_entries: tuple[RuntimeEntry, ...],
) -> None:
    result = logs_kb_search.search_entries(
        sample_runtime_entries,
        "INFO startup\njava.lang.IllegalStateException: Block is empty\n\tat deltix.qsrv.hf.tickdb.impl.Reader.read(Reader.java:42)\nINFO trailing",
    )

    assert result.normalized_query == (
        "java.lang.IllegalStateException: Block is empty\nat deltix.qsrv.hf.tickdb.impl.Reader.read(Reader.java:42)"
    )


def test_search_entries_can_match_on_search_text_only() -> None:
    entries = (
        RuntimeEntry(
            runtime_schema_version=1,
            id="nfs-timeout",
            symptom_signature="java.net.SocketTimeoutException at deltix.qsrv.store.RawReader.read",
            symptom_summary="A read times out while the server is accessing stream storage.",
            log_excerpt=None,
            root_cause="The storage backend is slow or unresponsive.",
            suggested_action="Check storage latency and retry after the backend recovers.",
            fix_version=None,
            fix_confidence="unknown",
            tags=("storage",),
            search_text="nfs latency storage mount timeout backend stalled",
        ),
    )

    result = logs_kb_search.search_entries(entries, "nfs mount stalled")

    assert [match.id for match in result.matches] == ["nfs-timeout"]


def test_search_entries_splits_single_line_container_logs() -> None:
    query = (
        "timebase-1  | 2026-09-01 10:14:13.948 INFO [main]: Cannot load license from server. "
        "Error: java.io.IOException timebase-1  | 2026-09-01 10:14:13.948 ERROR [main]: "
        "License invalid. Reason: It is impossible to establish connection with a License Server. "
        "timebase-1  | 2026-09-01 10:14:13.953 INFO [main]: "
        "TimeBase.network.socket.receiveBufferSize: 2524288 bytes (source: system property)"
    )

    normalized = logs_kb_search.normalize_query_text(query)

    assert normalized == (
        "Cannot load license from server. Error: java.io.IOException\n"
        "License invalid. Reason: It is impossible to establish connection with a License Server."
    )


@pytest.mark.parametrize("separator", [" \t  ", "\u2003", "\r\n"])
@pytest.mark.parametrize("container", ["", "timebase-1  | "])
def test_normalize_query_text_splits_headers_after_whitespace(
    separator: str, container: str
) -> None:
    query = (
        f"{container}2026-09-01 10:14:13.948 ERROR [main]: failed first"
        f"{separator}{container}2026-09-01 10:14:14.948 ERROR [main]: failed second"
    )

    assert logs_kb_search.normalize_query_text(query) == "failed first\nfailed second"


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("2026-09-01 10:14:13.948 ERROR [main]: - failed", "failed"),
        ("worker| ERROR [main]: failed", "failed"),
        ("a ERROR a ERROR a 2026/09/01 10:14:13 ERROR [main]: failed", "failed"),
        ("2026-09-01 10:14:13 ERROR original INFO [main]: chosen", "chosen"),
        ("ERROR original INFO later", "original INFO later"),
        ("INFOinitialized", "initialized"),
        ("body INFO words ERROR not a header", "body INFO words ERROR not a header"),
    ],
)
def test_normalize_query_text_preserves_log_level_header_rules(
    query: str, expected: str
) -> None:
    assert logs_kb_search.normalize_query_text(query) == expected


@pytest.mark.parametrize(
    ("query", "broad"),
    [
        ("java.lang.IllegalStateException", True),
        ("a..$FooError", True),
        ("Error.Exception", True),
        ("(FooException)", True),
        ("FooException failed", True),
        ("Exception", False),
        ("$Error", False),
        ("éFooException", False),
        ("é.FooException", False),
        ("FooExceptioné", False),
        ("FooException_", False),
        ("FooException$trailing", False),
    ],
)
def test_query_advice_preserves_exception_name_boundaries(
    query: str, broad: bool
) -> None:
    expected = (
        [
            "query looks broad; add the first stack frame or adjacent error lines to improve precision"
        ]
        if broad
        else []
    )

    assert logs_kb_search.query_advice(query, query) == expected


@pytest.mark.parametrize(
    "query",
    [
        pytest.param("Error: x" + " " * 100_000 + "x", id="whitespace"),
        pytest.param("a." * 50_000 + "z", id="dotted-name"),
        pytest.param("a " + "ERROR a " * 12_500, id="false-level-markers"),
    ],
)
def test_normalize_query_text_handles_long_non_headers(query: str) -> None:
    subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys\n"
                "from timebase_mcp.services.logs_kb.search import normalize_query_text\n"
                "query = sys.stdin.read()\n"
                "assert normalize_query_text(query) == query[:900].rstrip()\n"
            ),
        ],
        input=query,
        text=True,
        timeout=5,
        check=True,
    )


def test_search_entries_prefers_license_matches_for_license_connectivity_query() -> (
    None
):
    entries = (
        RuntimeEntry(
            runtime_schema_version=1,
            id="license-connectivity",
            symptom_signature="at deltix.util.license.OnlineLicenseClient.openReader(OnlineLicenseClient.java:<n>)",
            symptom_summary="TimeBase startup hangs or stalls during license validation when the server cannot reach the online license service.",
            log_excerpt=(
                "Cannot load license from server\n"
                "License invalid. Reason: It is impossible to establish connection with a License Server."
            ),
            root_cause="The server cannot reach the online license service during license validation.",
            suggested_action="Check outbound HTTPS connectivity to the license service and confirm a valid local license is available.",
            fix_version=None,
            fix_confidence="unknown",
            tags=("license", "network"),
            search_text="license server online license validation cannot load license connection failed",
        ),
        RuntimeEntry(
            runtime_schema_version=1,
            id="license-cache-path",
            symptom_signature="java.io.IOException at java.io.UnixFileSystem.createFileExclusively",
            symptom_summary="Startup logs `Cannot save license on a local drive` with `No such file or directory` while caching the license file.",
            log_excerpt=(
                "java.io.IOException: No such file or directory\n"
                "at java.io.UnixFileSystem.createFileExclusively(native)\n"
                "at deltix.util.license.LicenseClient.saveLicense(LicenseClient.java:351)"
            ),
            root_cause="The local path used to save the cached license file does not exist.",
            suggested_action="Verify that the configured QuantServer home or license cache directory exists and is writable.",
            fix_version=None,
            fix_confidence="unknown",
            tags=("license",),
            search_text="cannot save license local drive no such file or directory license cache path",
        ),
        RuntimeEntry(
            runtime_schema_version=1,
            id="generic-io-startup",
            symptom_signature="java.io.IOException at org.apache.catalina.startup.ExpandWar.expand",
            symptom_summary="TimeBase startup fails when Tomcat cannot create the exploded webapp directory under the home work path.",
            log_excerpt=(
                "QuantServer Version: 5.3.53\n"
                "QuantServer Home: /var/lib/market-data-node/timebase\n"
                "Opening and warming up TimeBase in /var/lib/market-data-node/timebase/timebase ..."
            ),
            root_cause="The TimeBase home layout is not in the expected state for startup.",
            suggested_action="Verify the TimeBase home has the expected directory structure.",
            fix_version=None,
            fix_confidence="unknown",
            tags=(),
            search_text="startup warming up timebase tomcat webapp ioexception",
        ),
    )
    query = (
        "timebase-1  | 2026-09-01 10:14:13.948 INFO [main]: Cannot load license from server. "
        "Error: java.io.IOException timebase-1  | 2026-09-01 10:14:13.948 ERROR [main]: "
        "License invalid. Reason: It is impossible to establish connection with a License Server. "
        "timebase-1  | 2026-09-01 10:14:13.953 INFO [main]: "
        "TimeBase.network.socket.receiveBufferSize: 2524288 bytes (source: system property)"
    )

    result = logs_kb_search.search_entries(entries, query, limit=3)

    assert result.normalized_query == (
        "Cannot load license from server. Error: java.io.IOException\n"
        "License invalid. Reason: It is impossible to establish connection with a License Server."
    )
    assert [match.id for match in result.matches] == [
        "license-connectivity",
        "license-cache-path",
        "generic-io-startup",
    ]


def test_search_entries_downranks_generic_exception_signatures_without_stack_frames() -> (
    None
):
    entries = (
        RuntimeEntry(
            runtime_schema_version=1,
            id="license-network",
            symptom_signature="at deltix.util.license.OnlineLicenseClient.openReader(OnlineLicenseClient.java:<n>)",
            symptom_summary="Startup hangs during online license validation when the server cannot reach the license service.",
            log_excerpt=(
                "Cannot load license from server\n"
                "License invalid. Reason: It is impossible to establish connection with a License Server."
            ),
            root_cause="The server cannot reach the online license service during license validation.",
            suggested_action="Check outbound connectivity to the license service.",
            fix_version=None,
            fix_confidence="unknown",
            tags=("license", "network"),
            search_text="license server cannot load license connection failed online license",
        ),
        RuntimeEntry(
            runtime_schema_version=1,
            id="generic-io",
            symptom_signature="java.io.IOException at org.apache.catalina.startup.ExpandWar.expand",
            symptom_summary="Startup fails with a generic IOException.",
            log_excerpt="java.io.IOException: startup failed",
            root_cause="A startup path hits a generic IO failure.",
            suggested_action="Check startup logs for the real cause.",
            fix_version=None,
            fix_confidence="unknown",
            tags=(),
            search_text="startup ioexception startup failed generic io",
        ),
    )
    query = (
        "timebase-1  | 2026-09-01 10:14:13.948 INFO [main]: Cannot load license from server. "
        "Error: java.io.IOException timebase-1  | 2026-09-01 10:14:13.948 ERROR [main]: "
        "License invalid. Reason: It is impossible to establish connection with a License Server."
    )

    result = logs_kb_search.search_entries(entries, query, limit=2)

    assert [match.id for match in result.matches] == ["license-network", "generic-io"]


def test_search_logs_kb_uses_runtime_loader(
    monkeypatch: pytest.MonkeyPatch,
    sample_runtime_entries: tuple[RuntimeEntry, ...],
) -> None:
    monkeypatch.setattr(
        logs_kb_search, "load_runtime_entries", lambda: sample_runtime_entries
    )

    result = logs_kb_search.search_logs_kb(
        "java.lang.IllegalStateException: Block is empty\n\tat deltix.qsrv.hf.tickdb.impl.Reader.read(Reader.java:42)",
    )

    assert result.matches[0].id == "block-empty"
