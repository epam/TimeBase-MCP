from __future__ import annotations

import base64
import json
from binascii import Error as BinasciiError
from typing import Any

from timebase_mcp.clients.base import TimeBaseClient
from timebase_mcp.models.core import (
    StreamInfo,
    StreamSchema,
    StreamSpaces,
    StreamSpaceTimeRange,
    StreamSymbols,
    StreamTimeRange,
)
from timebase_mcp.services.previews import format_messages_preview

_DEFAULT_STREAM_SYMBOLS_PAGE_SIZE = 100
_MAX_STREAM_SYMBOLS_PAGE_SIZE = 500


def list_streams(client: TimeBaseClient) -> list[StreamInfo]:
    """Return streams in deterministic key order.

    Adapter implementations return streams in their native order; service
    orchestration owns sorting before exposing results to tools/resources.
    """
    return sorted(client.list_stream_infos(), key=lambda stream: stream.key)


def get_stream_schema(client: TimeBaseClient, stream_key: str) -> StreamSchema:
    stream = client.get_stream(stream_key)
    return StreamSchema(
        stream_key=stream_key,
        schema_text=client.get_stream_schema_text(stream),
    )


def get_stream_symbols(
    client: TimeBaseClient,
    stream_key: str,
    limit: int = _DEFAULT_STREAM_SYMBOLS_PAGE_SIZE,
    cursor: str | None = None,
) -> StreamSymbols:
    if limit < 1:
        raise ValueError("limit must be at least 1.")

    page_size = min(limit, _MAX_STREAM_SYMBOLS_PAGE_SIZE)
    offset, cursor_total_symbols = _decode_stream_symbols_cursor(cursor, stream_key)
    stream = client.get_stream(stream_key)
    # Adapter symbol order is implementation-defined; service output is stable.
    symbols = sorted(client.list_stream_symbols(stream))
    total_symbols = len(symbols)
    symbols_changed_since_cursor = (
        cursor is not None
        and cursor_total_symbols is not None
        and cursor_total_symbols != total_symbols
    )
    page_symbols = symbols[offset : offset + page_size]
    next_offset = offset + len(page_symbols)
    next_cursor = (
        _encode_stream_symbols_cursor(
            stream_key=stream_key,
            offset=next_offset,
            total_symbols=total_symbols,
        )
        if next_offset < total_symbols
        else None
    )

    return StreamSymbols(
        stream_key=stream_key,
        symbols=page_symbols,
        returned_count=len(page_symbols),
        symbols_changed_since_cursor=symbols_changed_since_cursor,
        next_cursor=next_cursor,
    )


def get_stream_time_range(client: TimeBaseClient, stream_key: str) -> StreamTimeRange:
    stream = client.get_stream(stream_key)
    start, end = client.get_stream_time_range(stream_key, stream)

    return StreamTimeRange(
        stream_key=stream_key,
        start=start,
        end=end,
    )


def get_stream_spaces(client: TimeBaseClient, stream_key: str) -> StreamSpaces:
    stream = client.get_stream(stream_key)
    spaces = client.list_stream_spaces(stream)

    if spaces is None:
        return StreamSpaces(
            stream_key=stream_key,
            supports_spaces=False,
        )

    # Adapter space order is implementation-defined; service output is stable.
    sorted_spaces = sorted(spaces)
    return StreamSpaces(
        stream_key=stream_key,
        spaces=sorted_spaces,
        returned_count=len(sorted_spaces),
        supports_spaces=True,
    )


def get_stream_space_time_range(
    client: TimeBaseClient,
    stream_key: str,
    space: str,
) -> StreamSpaceTimeRange:
    stream = client.get_stream(stream_key)
    start, end = client.get_stream_space_time_range(stream_key, stream, space)

    return StreamSpaceTimeRange(
        stream_key=stream_key,
        space=space,
        start=start,
        end=end,
    )


def get_stream_messages_text(
    client: TimeBaseClient,
    stream_key: str,
    reverse: bool = False,
    count: int = 10,
    space: str | None = None,
) -> str:
    if count < 1:
        raise ValueError("count must be at least 1.")

    stream = client.get_stream(stream_key)
    messages = client.read_stream_messages(stream, reverse, count, space)
    client.raise_if_cancelled()

    return _format_stream_messages_preview(
        stream_key=stream_key,
        reverse=reverse,
        count=count,
        space=space,
        messages=messages,
    )


def _format_stream_messages_preview(
    stream_key: str,
    reverse: bool,
    count: int,
    space: str | None,
    messages: list[dict[str, Any]],
) -> str:
    direction = "last" if reverse else "first"
    header_lines = [
        f"Stream: {stream_key}",
        f"Showing {len(messages)} of requested {count} {direction} messages",
    ]
    if space is not None:
        header_lines.insert(1, f"Space: {space or '<default>'}")

    return format_messages_preview(
        header_lines=header_lines,
        messages=messages,
        empty_text="No messages found.",
    )


def _encode_stream_symbols_cursor(
    stream_key: str,
    offset: int,
    total_symbols: int,
) -> str:
    cursor_payload = json.dumps(
        {
            "stream_key": stream_key,
            "offset": offset,
            "total_symbols": total_symbols,
        },
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(cursor_payload).decode("ascii").rstrip("=")


def _decode_stream_symbols_cursor(
    cursor: str | None,
    expected_stream_key: str,
) -> tuple[int, int | None]:
    if cursor is None:
        return 0, None

    try:
        padding = "=" * (-len(cursor) % 4)
        decoded_payload = base64.urlsafe_b64decode(cursor + padding).decode("utf-8")
        payload = json.loads(decoded_payload)
    except (ValueError, UnicodeDecodeError, BinasciiError) as exc:
        raise ValueError("Invalid cursor.") from exc

    offset = payload.get("offset")
    stream_key = payload.get("stream_key")
    total_symbols = payload.get("total_symbols")
    if (
        not isinstance(offset, int)
        or offset < 0
        or not isinstance(stream_key, str)
        or stream_key != expected_stream_key
    ):
        raise ValueError("Invalid cursor.")

    if total_symbols is not None and (
        not isinstance(total_symbols, int) or total_symbols < 0
    ):
        raise ValueError("Invalid cursor.")

    return offset, total_symbols
