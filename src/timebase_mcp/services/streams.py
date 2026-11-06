from __future__ import annotations

import base64
import json
from typing import Any

from pydantic import BaseModel, Field

from timebase_mcp.clients.base import TimeBaseClient
from timebase_mcp.models.core import (
    StreamCatalog,
    StreamSchema,
    StreamSpaces,
    StreamSpaceTimeRange,
    StreamSymbols,
    StreamTimeRange,
)
from timebase_mcp.services.previews import format_messages_preview
from timebase_mcp.version import get_version

_DEFAULT_LIMIT = 100
_MAX_LIMIT = 500
_CURSOR_VERSION = 5
_MCP_VERSION = get_version()


class _Cursor(BaseModel):
    cursor_version: int
    mcp_version: str
    instance_key: str
    stream_key: str | None
    offset: int = Field(ge=0)
    total: int = Field(ge=0)


def list_streams(
    client: TimeBaseClient,
    limit: int = _DEFAULT_LIMIT,
    cursor: str | None = None,
) -> StreamCatalog:
    if limit < 1:
        raise ValueError("limit must be at least 1.")
    limit = min(limit, _MAX_LIMIT)
    offset, previous_total = _decode_cursor(cursor, client)
    if offset > 2**31 - 1 - limit:
        raise ValueError("Invalid cursor: stream offset is out of range.")
    total, streams = client.list_stream_infos(offset, limit)
    client.raise_if_cancelled()
    offset += len(streams)
    next_cursor = None
    if offset < total:
        next_cursor = _encode_cursor(client, offset, total)

    return StreamCatalog(
        streams=streams,
        total_streams=total,
        returned_count=len(streams),
        streams_changed_since_cursor=previous_total is not None
        and previous_total != total,
        next_cursor=next_cursor,
    )


def get_stream_catalog_text(client: TimeBaseClient) -> str:
    catalog = list_streams(client)
    if not catalog.streams:
        return "No streams found."
    text = "\n".join(
        f"{stream.key}: {stream.description or 'No description'}"
        for stream in catalog.streams
    )
    if catalog.next_cursor is not None:
        arguments = json.dumps(
            {"instance_key": client.instance_key, "cursor": catalog.next_cursor}
        )
        text += (
            f"\n\nShowing {catalog.returned_count} of {catalog.total_streams} streams."
            f"\nContinue with list_streams using arguments: {arguments}"
        )
    return text


def get_stream_schema(client: TimeBaseClient, stream_key: str) -> StreamSchema:
    stream = client.get_stream(stream_key)
    return StreamSchema(
        stream_key=stream_key,
        schema_text=client.get_stream_schema_text(stream),
    )


def get_stream_symbols(
    client: TimeBaseClient,
    stream_key: str,
    limit: int = _DEFAULT_LIMIT,
    cursor: str | None = None,
) -> StreamSymbols:
    if limit < 1:
        raise ValueError("limit must be at least 1.")

    limit = min(limit, _MAX_LIMIT)
    offset, previous_total = _decode_cursor(cursor, client, stream_key=stream_key)
    if offset > 2**31 - 1 - limit:
        raise ValueError("Invalid cursor: symbol page offset is out of range.")
    total, symbols = client.list_stream_symbols(stream_key, offset, limit)
    client.raise_if_cancelled()
    offset += len(symbols)
    next_cursor = None
    if offset < total:
        next_cursor = _encode_cursor(client, offset, total, stream_key=stream_key)

    return StreamSymbols(
        stream_key=stream_key,
        symbols=symbols,
        returned_count=len(symbols),
        symbols_changed_since_cursor=previous_total is not None
        and previous_total != total,
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


def _encode_cursor(
    client: TimeBaseClient,
    offset: int,
    total: int,
    *,
    stream_key: str | None = None,
) -> str:
    payload = _Cursor(
        cursor_version=_CURSOR_VERSION,
        mcp_version=_MCP_VERSION,
        instance_key=client.instance_key,
        stream_key=stream_key,
        offset=offset,
        total=total,
    ).model_dump_json()
    return base64.urlsafe_b64encode(payload.encode()).decode("ascii").rstrip("=")


def _decode_cursor(
    cursor: str | None,
    client: TimeBaseClient,
    *,
    stream_key: str | None = None,
) -> tuple[int, int | None]:
    if cursor is None:
        return 0, None

    try:
        padding = "=" * (-len(cursor) % 4)
        payload = _Cursor.model_validate_json(
            base64.b64decode(cursor + padding, altchars=b"-_", validate=True),
            strict=True,
        )
    except ValueError as exc:
        raise ValueError(
            "Invalid cursor. Restart pagination without a cursor."
        ) from exc

    if (payload.cursor_version, payload.mcp_version) != (_CURSOR_VERSION, _MCP_VERSION):
        raise ValueError("Invalid cursor version. Restart pagination without a cursor.")
    if payload.instance_key != client.instance_key:
        raise ValueError(
            "This stream cursor belongs to a different TimeBase instance. Restart pagination without a cursor."
        )
    if payload.stream_key != stream_key:
        raise ValueError(
            "Invalid cursor: this cursor belongs to a different stream or tool. Restart pagination without a cursor."
        )

    return payload.offset, payload.total
