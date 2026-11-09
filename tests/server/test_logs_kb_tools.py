from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager

import pytest
from mcp.client import Client
from mcp_types import TextContent

from timebase_mcp.config.settings import MCPSettings
from timebase_mcp.errors import ConfigurationError
from timebase_mcp.models.logs_kb import SearchLogsKBResult
from timebase_mcp.server import create_server
from timebase_mcp.services.logs_kb.search import MAX_RAW_QUERY_CHARACTERS
from timebase_mcp.tools import logs_kb as logs_kb_tools

_SEARCH_LOGS_KB_TARGET = "search_logs_kb_service"


@pytest.mark.anyio
async def test_call_search_logs_kb_tool_returns_structured_payload(
    monkeypatch: pytest.MonkeyPatch,
    client_session_factory: Callable[
        [MCPSettings | None],
        AbstractAsyncContextManager[Client],
    ],
) -> None:
    def search_logs_kb(*, query: str, limit: int):
        assert query == "java.lang.IllegalStateException: Block is empty"
        assert limit == 3
        return {
            "query": query,
            "normalized_query": query,
            "advice": [],
            "matches": [
                {
                    "id": "block-empty",
                    "symptom_signature": "java.lang.IllegalStateException at deltix.Reader.read",
                    "symptom_summary": "A read fails with IllegalStateException while scanning stream data.",
                    "root_cause": "The stream contains an empty or incomplete data block.",
                    "suggested_action": "Check the affected stream for damaged data and restore it from backup if needed.",
                    "fix_version": "5.7.16",
                    "fix_confidence": "likely",
                    "tags": ["storage", "cursor"],
                }
            ],
        }

    monkeypatch.setattr(logs_kb_tools, _SEARCH_LOGS_KB_TARGET, search_logs_kb)

    async with client_session_factory(None) as client_session:
        result = await client_session.call_tool(
            "search_logs_kb",
            {"query": "java.lang.IllegalStateException: Block is empty", "limit": 3},
        )

    assert result.is_error is False
    assert result.structured_content == {
        "query": "java.lang.IllegalStateException: Block is empty",
        "normalized_query": "java.lang.IllegalStateException: Block is empty",
        "advice": [],
        "matches": [
            {
                "id": "block-empty",
                "symptom_signature": "java.lang.IllegalStateException at deltix.Reader.read",
                "symptom_summary": "A read fails with IllegalStateException while scanning stream data.",
                "root_cause": "The stream contains an empty or incomplete data block.",
                "suggested_action": "Check the affected stream for damaged data and restore it from backup if needed.",
                "fix_version": "5.7.16",
                "fix_confidence": "likely",
                "tags": ["storage", "cursor"],
            }
        ],
    }


@pytest.mark.anyio
async def test_search_logs_kb_tool_query_limit_accepts_unicode_boundary(
    monkeypatch: pytest.MonkeyPatch,
    client_session_factory: Callable[
        [MCPSettings | None],
        AbstractAsyncContextManager[Client],
    ],
) -> None:
    received_queries: list[str] = []

    def search_logs_kb(*, query: str, limit: int) -> SearchLogsKBResult:
        received_queries.append(query)
        return SearchLogsKBResult(query="stub query", normalized_query="stub query")

    monkeypatch.setattr(logs_kb_tools, _SEARCH_LOGS_KB_TARGET, search_logs_kb)
    query = " " + "💥" * (MAX_RAW_QUERY_CHARACTERS - 2) + " "

    async with client_session_factory(None) as client_session:
        tools = await client_session.list_tools()
        tool = next(tool for tool in tools.tools if tool.name == "search_logs_kb")
        assert (
            tool.input_schema["properties"]["query"]["maxLength"]
            == MAX_RAW_QUERY_CHARACTERS
        )
        result = await client_session.call_tool("search_logs_kb", {"query": query})

    assert result.is_error is False
    assert received_queries == [query]


@pytest.mark.parametrize(
    "character", ["x", "💥", " "], ids=["ascii", "unicode", "whitespace"]
)
@pytest.mark.anyio
async def test_search_logs_kb_tool_rejects_oversized_query_before_search(
    character: str,
    monkeypatch: pytest.MonkeyPatch,
    client_session_factory: Callable[
        [MCPSettings | None],
        AbstractAsyncContextManager[Client],
    ],
) -> None:
    def search_logs_kb(*, query: str, limit: int) -> SearchLogsKBResult:
        pytest.fail("Oversized queries must be rejected before search")

    monkeypatch.setattr(logs_kb_tools, _SEARCH_LOGS_KB_TARGET, search_logs_kb)

    async with client_session_factory(None) as client_session:
        result = await client_session.call_tool(
            "search_logs_kb", {"query": character * (MAX_RAW_QUERY_CHARACTERS + 1)}
        )

    assert result.is_error is True
    assert result.structured_content is None


@pytest.mark.anyio
async def test_call_search_logs_kb_tool_surfaces_configuration_errors_to_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_search_logs_kb(*, query: str, limit: int):
        _ = (query, limit)
        raise ConfigurationError("Bundled logs KB runtime artifact is not available.")

    monkeypatch.setattr(logs_kb_tools, _SEARCH_LOGS_KB_TARGET, fail_search_logs_kb)

    server = create_server(MCPSettings())
    async with Client(server, raise_exceptions=False) as client_session:
        result = await client_session.call_tool(
            "search_logs_kb",
            {"query": "java.lang.IllegalStateException"},
        )

    text_content = [
        content.text for content in result.content if isinstance(content, TextContent)
    ]

    assert result.is_error is True
    assert result.structured_content is None
    assert text_content == [
        "Error executing tool search_logs_kb: Bundled logs KB runtime artifact is not available."
    ]


@pytest.mark.anyio
async def test_call_search_logs_kb_tool_surfaces_invalid_query_to_client(
    client_session_factory: Callable[
        [MCPSettings | None],
        AbstractAsyncContextManager[Client],
    ],
) -> None:
    async with client_session_factory(None) as client_session:
        result = await client_session.call_tool(
            "search_logs_kb",
            {"query": "   "},
        )

    text_content = [
        content.text for content in result.content if isinstance(content, TextContent)
    ]

    assert result.is_error is True
    assert result.structured_content is None
    assert text_content == [
        "Error executing tool search_logs_kb: query must be a non-empty string"
    ]
