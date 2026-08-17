from __future__ import annotations

import base64
import json
from datetime import datetime, timezone
from typing import Any

import pytest
from typing_extensions import override

from tests.stubs import StubTimeBaseClient, stub_instance
from timebase_mcp.errors import StreamNotFoundError
from timebase_mcp.services import streams as stream_service


class StubStream:
    def __init__(
        self,
        *,
        spaces: list[str] | None = None,
        time_range: list[int] | None = None,
        space_time_ranges: dict[str, list[int] | None] | None = None,
        symbols: list[str] | None = None,
    ) -> None:
        self.spaces = spaces
        self.time_range = time_range
        self.space_time_ranges = space_time_ranges or {}
        self.symbols = symbols or []


class StubClient(StubTimeBaseClient):
    def __init__(self, stream: StubStream) -> None:
        super().__init__(stub_instance())
        self.stream = stream
        self.read_messages_calls: list[tuple[bool, int, str | None]] = []

    @override
    def get_stream(self, stream_key: str) -> StubStream:
        assert stream_key == "bars"
        return self.stream

    @override
    def get_stream_schema_text(self, stream: Any) -> str:
        return "schema"

    @override
    def list_stream_symbols(self, stream: StubStream) -> list[str]:
        return list(stream.symbols)

    @override
    def get_stream_time_range(
        self,
        stream_key: str,
        stream: StubStream,
    ) -> tuple[datetime | None, datetime | None]:
        if stream.time_range is None:
            return None, None
        start_ms, end_ms = stream.time_range
        return (
            datetime.fromtimestamp(start_ms / 1000, tz=timezone.utc),
            datetime.fromtimestamp(end_ms / 1000, tz=timezone.utc),
        )

    @override
    def list_stream_spaces(self, stream: StubStream) -> list[str] | None:
        return stream.spaces

    @override
    def get_stream_space_time_range(
        self,
        stream_key: str,
        stream: StubStream,
        space: str,
    ) -> tuple[datetime | None, datetime | None]:
        time_range = stream.space_time_ranges.get(space)
        if time_range is None:
            return None, None
        start_ms, end_ms = time_range
        return (
            datetime.fromtimestamp(start_ms / 1000, tz=timezone.utc),
            datetime.fromtimestamp(end_ms / 1000, tz=timezone.utc),
        )

    @override
    def read_stream_messages(
        self,
        stream: Any,
        reverse: bool,
        count: int,
        space: str | None,
    ) -> list[dict[str, Any]]:
        self.read_messages_calls.append((reverse, count, space))
        return [{"symbol": "AAPL"}]


class _MissingStreamClient(StubTimeBaseClient):
    @override
    def get_stream(self, stream_key: str) -> StubStream:
        raise StreamNotFoundError(stream_key)


def _cursor_for(stream_key: str, offset: int, total_symbols: int) -> str:
    payload = json.dumps(
        {
            "stream_key": stream_key,
            "offset": offset,
            "total_symbols": total_symbols,
        },
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def test_get_stream_time_range_returns_utc_datetimes() -> None:
    client = StubClient(StubStream(time_range=[1_700_000_000_000, 1_700_000_060_000]))

    result = stream_service.get_stream_time_range(client, "bars")

    assert result.stream_key == "bars"
    assert result.start == datetime(2023, 11, 14, 22, 13, 20, tzinfo=timezone.utc)
    assert result.end == datetime(2023, 11, 14, 22, 14, 20, tzinfo=timezone.utc)


def test_get_stream_spaces_reports_unsupported_when_dxapi_returns_none() -> None:
    client = StubClient(StubStream(spaces=None))

    result = stream_service.get_stream_spaces(client, "bars")

    assert result.stream_key == "bars"
    assert result.spaces == []
    assert result.returned_count == 0
    assert result.supports_spaces is False


def test_get_stream_spaces_preserves_default_space_and_sorts() -> None:
    client = StubClient(StubStream(spaces=["blue", "", "red"]))

    result = stream_service.get_stream_spaces(client, "bars")

    assert result.spaces == ["", "blue", "red"]
    assert result.returned_count == 3
    assert result.supports_spaces is True


def test_get_stream_space_time_range_returns_utc_datetimes() -> None:
    client = StubClient(
        StubStream(
            space_time_ranges={
                "blue": [1_700_000_000_000, 1_700_000_060_000],
            },
        )
    )

    result = stream_service.get_stream_space_time_range(client, "bars", "blue")

    assert result.stream_key == "bars"
    assert result.space == "blue"
    assert result.start == datetime(2023, 11, 14, 22, 13, 20, tzinfo=timezone.utc)
    assert result.end == datetime(2023, 11, 14, 22, 14, 20, tzinfo=timezone.utc)


def test_get_stream_messages_text_passes_space_to_reader() -> None:
    client = StubClient(StubStream(spaces=["blue"]))

    text = stream_service.get_stream_messages_text(
        client, "bars", reverse=True, count=1, space="blue"
    )

    assert client.read_messages_calls == [(True, 1, "blue")]
    assert "Stream: bars" in text
    assert "Space: blue" in text


def test_get_stream_symbols_sorts_and_pages() -> None:
    client = StubClient(StubStream(symbols=["z", "a", "m"]))

    first = stream_service.get_stream_symbols(client, "bars", limit=1)

    assert first.symbols == ["a"]
    assert first.returned_count == 1
    assert first.next_cursor is not None
    assert first.symbols_changed_since_cursor is False

    second = stream_service.get_stream_symbols(
        client, "bars", limit=1, cursor=first.next_cursor
    )
    assert second.symbols == ["m"]
    assert second.next_cursor is not None

    third = stream_service.get_stream_symbols(
        client, "bars", limit=1, cursor=second.next_cursor
    )
    assert third.symbols == ["z"]
    assert third.next_cursor is None


def test_get_stream_symbols_rejects_non_positive_limit() -> None:
    client = StubClient(StubStream(symbols=["a"]))

    with pytest.raises(ValueError, match="limit must be at least 1"):
        stream_service.get_stream_symbols(client, "bars", limit=0)


def test_get_stream_symbols_caps_page_size_at_500() -> None:
    symbols = [f"s{index:04d}" for index in range(600)]
    client = StubClient(StubStream(symbols=symbols))

    result = stream_service.get_stream_symbols(client, "bars", limit=1000)

    assert result.returned_count == 500
    assert len(result.symbols) == 500
    assert result.next_cursor is not None


def test_get_stream_symbols_rejects_invalid_cursor() -> None:
    client = StubClient(StubStream(symbols=["a", "b"]))

    with pytest.raises(ValueError, match="Invalid cursor"):
        stream_service.get_stream_symbols(client, "bars", cursor="%%%")

    other_stream_cursor = _cursor_for("other", offset=1, total_symbols=2)
    with pytest.raises(ValueError, match="Invalid cursor"):
        stream_service.get_stream_symbols(
            client, "bars", cursor=other_stream_cursor
        )


def test_get_stream_symbols_reports_changed_symbol_set() -> None:
    stream = StubStream(symbols=["z", "a", "m"])
    client = StubClient(stream)
    first = stream_service.get_stream_symbols(client, "bars", limit=1)
    assert first.next_cursor is not None

    stream.symbols = ["z", "a", "m", "extra"]
    second = stream_service.get_stream_symbols(
        client, "bars", limit=1, cursor=first.next_cursor
    )

    assert second.symbols_changed_since_cursor is True


def test_stream_not_found_propagates_from_schema_and_symbols() -> None:
    client = _MissingStreamClient()

    with pytest.raises(StreamNotFoundError, match="Stream 'bars' was not found"):
        stream_service.get_stream_schema(client, "bars")

    with pytest.raises(StreamNotFoundError, match="Stream 'bars' was not found"):
        stream_service.get_stream_symbols(client, "bars")
