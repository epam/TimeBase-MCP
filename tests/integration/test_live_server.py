from __future__ import annotations

import pytest
from mcp.client import Client
from mcp_types import TextContent, TextResourceContents

from tests.integration.support import SeededStream
from timebase_mcp.models.core import (
    CompileQQLResult,
    StreamCatalog,
    StreamSchema,
    StreamSymbols,
    StreamTimeRange,
)

pytestmark = pytest.mark.integration


def _tool_text(result) -> str:
    return "\n".join(
        content.text for content in result.content if isinstance(content, TextContent)
    )


def _resource_text(result) -> str:
    return "\n".join(
        content.text
        for content in result.contents
        if isinstance(content, TextResourceContents)
    )


@pytest.mark.anyio
@pytest.mark.usefixtures("seeded_catalog")
async def test_list_streams_and_stream_catalog_show_the_same_first_page(
    client_session: Client,
) -> None:
    tool_result = await client_session.call_tool("list_streams", {})
    assert tool_result.is_error is False
    catalog = StreamCatalog.model_validate(tool_result.structured_content)
    assert catalog.total_streams >= 2
    assert catalog.returned_count == len(catalog.streams)
    assert catalog.returned_count == min(100, catalog.total_streams)

    first_result = await client_session.call_tool("list_streams", {"limit": 1})
    assert first_result.is_error is False
    first = StreamCatalog.model_validate(first_result.structured_content)
    assert first.next_cursor is not None
    second_result = await client_session.call_tool(
        "list_streams", {"limit": 1, "cursor": first.next_cursor}
    )
    assert second_result.is_error is False
    second = StreamCatalog.model_validate(second_result.structured_content)
    assert first.returned_count == second.returned_count == 1
    assert first.total_streams == second.total_streams == catalog.total_streams
    assert first.streams + second.streams == catalog.streams[:2]
    assert first.streams[0].key != second.streams[0].key

    resource_result = await client_session.read_resource("timebase://streams")
    resource_text = _resource_text(resource_result)

    expected_text = "\n".join(
        f"{stream.key}: {stream.description or 'No description'}"
        for stream in catalog.streams
    )
    assert resource_text.startswith(expected_text)


@pytest.mark.anyio
async def test_stream_schema_tool_and_resource_return_ddl(
    client_session: Client,
    seeded_stream: SeededStream,
) -> None:
    tool_result = await client_session.call_tool(
        "get_stream_schema",
        {"stream_key": seeded_stream.stream_key},
    )
    assert tool_result.is_error is False
    stream_schema = StreamSchema.model_validate(tool_result.structured_content)
    assert stream_schema.stream_key == seeded_stream.stream_key
    assert "DURABLE STREAM" in stream_schema.schema_text
    assert "BarMessage" in stream_schema.schema_text

    resource_result = await client_session.read_resource(
        f"timebase://streams/{seeded_stream.stream_key}/schema"
    )
    resource_text = _resource_text(resource_result)

    assert "DURABLE STREAM" in resource_text
    assert seeded_stream.stream_key in resource_text


@pytest.mark.anyio
async def test_stream_time_range_matches_seeded_window(
    client_session: Client,
    seeded_stream: SeededStream,
) -> None:
    result = await client_session.call_tool(
        "get_stream_time_range",
        {"stream_key": seeded_stream.stream_key},
    )
    assert result.is_error is False
    time_range = StreamTimeRange.model_validate(result.structured_content)
    assert time_range.stream_key == seeded_stream.stream_key
    assert time_range.start == seeded_stream.first_timestamp
    assert time_range.end == seeded_stream.last_timestamp


@pytest.mark.anyio
async def test_stream_symbols_are_paginated_deterministically(
    client_session: Client,
    seeded_stream: SeededStream,
) -> None:
    first_page = await client_session.call_tool(
        "get_stream_symbols",
        {"stream_key": seeded_stream.stream_key, "limit": 1},
    )
    assert first_page.is_error is False
    first_symbols = StreamSymbols.model_validate(first_page.structured_content)
    assert first_symbols.symbols == [seeded_stream.symbols[0]]
    assert first_symbols.returned_count == 1
    assert first_symbols.symbols_changed_since_cursor is False
    assert first_symbols.next_cursor is not None

    second_page = await client_session.call_tool(
        "get_stream_symbols",
        {
            "stream_key": seeded_stream.stream_key,
            "limit": 1,
            "cursor": first_symbols.next_cursor,
        },
    )
    assert second_page.is_error is False
    second_symbols = StreamSymbols.model_validate(second_page.structured_content)
    assert second_symbols.symbols == [seeded_stream.symbols[1]]
    assert second_symbols.returned_count == 1
    assert second_symbols.next_cursor is None


@pytest.mark.anyio
async def test_stream_messages_preview_first_and_last_messages(
    client_session: Client,
    seeded_stream: SeededStream,
) -> None:
    first_messages = await client_session.call_tool(
        "get_stream_messages",
        {"stream_key": seeded_stream.stream_key, "count": 2},
    )
    last_messages = await client_session.call_tool(
        "get_stream_messages",
        {"stream_key": seeded_stream.stream_key, "count": 1, "reverse": True},
    )

    assert first_messages.is_error is False
    first_text = _tool_text(first_messages)
    assert f"Stream: {seeded_stream.stream_key}" in first_text
    assert '"symbol": "AAPL"' in first_text
    assert '"symbol": "MSFT"' in first_text

    assert last_messages.is_error is False
    last_text = _tool_text(last_messages)
    assert "Showing 1 of requested 1 last messages" in last_text
    assert '"symbol": "AAPL"' in last_text
    assert seeded_stream.last_timestamp.isoformat() in last_text


@pytest.mark.anyio
async def test_execute_query_returns_seeded_rows(
    client_session: Client,
    seeded_stream: SeededStream,
) -> None:
    result = await client_session.call_tool(
        "execute_query",
        {
            "query": f'select * from "{seeded_stream.stream_key}"',
            "limit": 2,
        },
    )

    assert result.is_error is False
    text = _tool_text(result)
    assert f'Query: select * from "{seeded_stream.stream_key}"' in text
    assert "Showing 2 of requested 2 result rows" in text
    assert '"symbol": "AAPL"' in text
    assert '"symbol": "MSFT"' in text


@pytest.mark.anyio
async def test_compile_query_returns_compact_validation_result(
    client_session: Client,
    seeded_stream: SeededStream,
) -> None:
    query_text = f'select * from "{seeded_stream.stream_key}"'
    result = await client_session.call_tool(
        "compile_query",
        {"query": query_text},
    )
    assert result.is_error is False
    compile_result = CompileQQLResult.model_validate(result.structured_content)
    assert compile_result.valid is True
    assert compile_result.error is None
