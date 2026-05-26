from __future__ import annotations

from mcp.client.session import ClientSession
from mcp.types import TextContent, TextResourceContents
from pydantic import AnyUrl, TypeAdapter
import pytest

from tests.integration.support import SeededStream
from timebase_mcp.models import (
    CompileQQLResult,
    StreamInfo,
    StreamSchema,
    StreamSymbols,
    StreamTimeRange,
)


pytestmark = pytest.mark.integration


_LIST_STREAMS_ADAPTER = TypeAdapter(list[StreamInfo])
_RESOURCE_URI_ADAPTER = TypeAdapter(AnyUrl)


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


def _resource_uri(value: str) -> AnyUrl:
    return _RESOURCE_URI_ADAPTER.validate_python(value)


def _list_streams(result) -> list[StreamInfo]:
    structured_content = result.structuredContent or []
    if isinstance(structured_content, dict):
        structured_content = structured_content.get("result", [])
    return _LIST_STREAMS_ADAPTER.validate_python(structured_content)


def _stream_schema(result) -> StreamSchema:
    assert result.structuredContent is not None
    return StreamSchema.model_validate(result.structuredContent)


def _stream_time_range(result) -> StreamTimeRange:
    assert result.structuredContent is not None
    return StreamTimeRange.model_validate(result.structuredContent)


def _stream_symbols(result) -> StreamSymbols:
    assert result.structuredContent is not None
    return StreamSymbols.model_validate(result.structuredContent)


def _compile_query(result) -> CompileQQLResult:
    assert result.structuredContent is not None
    return CompileQQLResult.model_validate(result.structuredContent)


@pytest.mark.anyio
async def test_list_streams_and_stream_catalog_show_seeded_stream(
    client_session: ClientSession,
    seeded_stream: SeededStream,
) -> None:
    tool_result = await client_session.call_tool("list_streams", {})
    tool_streams = _list_streams(tool_result)

    assert tool_result.isError is False
    assert any(stream.key == seeded_stream.stream_key for stream in tool_streams)

    resource_result = await client_session.read_resource(
        _resource_uri("timebase://streams")
    )
    resource_text = _resource_text(resource_result)

    assert seeded_stream.stream_key in resource_text


@pytest.mark.anyio
async def test_stream_schema_tool_and_resource_return_ddl(
    client_session: ClientSession,
    seeded_stream: SeededStream,
) -> None:
    tool_result = await client_session.call_tool(
        "get_stream_schema",
        {"stream_key": seeded_stream.stream_key},
    )
    stream_schema = _stream_schema(tool_result)

    assert tool_result.isError is False
    assert stream_schema.stream_key == seeded_stream.stream_key
    assert "DURABLE STREAM" in stream_schema.schema_text
    assert "BarMessage" in stream_schema.schema_text

    resource_result = await client_session.read_resource(
        _resource_uri(f"timebase://streams/{seeded_stream.stream_key}/schema")
    )
    resource_text = _resource_text(resource_result)

    assert "DURABLE STREAM" in resource_text
    assert seeded_stream.stream_key in resource_text


@pytest.mark.anyio
async def test_stream_time_range_matches_seeded_window(
    client_session: ClientSession,
    seeded_stream: SeededStream,
) -> None:
    result = await client_session.call_tool(
        "get_stream_time_range",
        {"stream_key": seeded_stream.stream_key},
    )
    time_range = _stream_time_range(result)

    assert result.isError is False
    assert time_range.stream_key == seeded_stream.stream_key
    assert time_range.start == seeded_stream.first_timestamp
    assert time_range.end == seeded_stream.last_timestamp


@pytest.mark.anyio
async def test_stream_symbols_are_paginated_deterministically(
    client_session: ClientSession,
    seeded_stream: SeededStream,
) -> None:
    first_page = await client_session.call_tool(
        "get_stream_symbols",
        {"stream_key": seeded_stream.stream_key, "limit": 1},
    )
    first_symbols = _stream_symbols(first_page)

    assert first_page.isError is False
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
    second_symbols = _stream_symbols(second_page)

    assert second_page.isError is False
    assert second_symbols.symbols == [seeded_stream.symbols[1]]
    assert second_symbols.returned_count == 1
    assert second_symbols.next_cursor is None


@pytest.mark.anyio
async def test_stream_messages_preview_first_and_last_messages(
    client_session: ClientSession,
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

    assert first_messages.isError is False
    first_text = _tool_text(first_messages)
    assert f"Stream: {seeded_stream.stream_key}" in first_text
    assert '"symbol": "AAPL"' in first_text
    assert '"symbol": "MSFT"' in first_text

    assert last_messages.isError is False
    last_text = _tool_text(last_messages)
    assert "Showing 1 of requested 1 last messages" in last_text
    assert '"symbol": "AAPL"' in last_text
    assert seeded_stream.last_timestamp.isoformat() in last_text


@pytest.mark.anyio
async def test_execute_query_returns_seeded_rows(
    client_session: ClientSession,
    seeded_stream: SeededStream,
) -> None:
    result = await client_session.call_tool(
        "execute_query",
        {
            "query": f'select * from "{seeded_stream.stream_key}"',
            "limit": 2,
        },
    )

    assert result.isError is False
    text = _tool_text(result)
    assert f'Query: select * from "{seeded_stream.stream_key}"' in text
    assert "Showing 2 of requested 2 result rows" in text
    assert '"symbol": "AAPL"' in text
    assert '"symbol": "MSFT"' in text


@pytest.mark.anyio
async def test_compile_query_returns_compact_validation_result(
    client_session: ClientSession,
    seeded_stream: SeededStream,
) -> None:
    query_text = f'select * from "{seeded_stream.stream_key}"'
    result = await client_session.call_tool(
        "compile_query",
        {"query": query_text},
    )
    compile_result = _compile_query(result)

    assert result.isError is False
    assert compile_result.valid is True
    assert compile_result.error is None
