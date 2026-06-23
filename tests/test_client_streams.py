from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

from timebase_mcp.clients.base import TimeBaseClient
from timebase_mcp.errors import InvalidStreamTimeRangeError
from timebase_mcp.instance import TimeBaseInstanceConfig


class StubStream:
    def __init__(
        self,
        *,
        spaces: list[str] | None = None,
        time_range: list[int] | None = None,
        space_time_ranges: dict[str, list[int] | None] | None = None,
    ) -> None:
        self.spaces = spaces
        self.time_range = time_range
        self.space_time_ranges = space_time_ranges or {}


class StubClient(TimeBaseClient):
    def __init__(self, stream: StubStream) -> None:
        super().__init__(TimeBaseInstanceConfig(tb_url="dxtick://localhost:8011"))
        self.stream = stream
        self.read_messages_calls: list[tuple[bool, int, str | None]] = []

    def open(self) -> object:
        return object()

    def close(self) -> None:
        pass

    def _require_db(self) -> object:
        return object()

    def get_stream(self, stream_key: str) -> StubStream:
        assert stream_key == "bars"
        return self.stream

    def _get_stream_schema_text(self, stream: Any) -> str:
        return "schema"

    def _list_stream_symbols(self, stream: Any) -> list[str]:
        return []

    def _get_stream_time_range_ms(self, stream: StubStream) -> list[int] | None:
        return stream.time_range

    def _list_stream_spaces(self, stream: StubStream) -> list[str] | None:
        return stream.spaces

    def _get_stream_space_time_range_ms(
        self,
        stream: StubStream,
        space: str,
    ) -> list[int] | None:
        return stream.space_time_ranges.get(space)

    def _read_stream_messages(
        self,
        stream: Any,
        reverse: bool,
        count: int,
        space: str | None,
    ) -> list[dict[str, Any]]:
        self.read_messages_calls.append((reverse, count, space))
        return [{"symbol": "AAPL"}]

    def _read_query_messages(self, query_text: str, limit: int) -> list[dict[str, Any]]:
        return []

    def _compile_query_tokens(self, query_text: str) -> list[Any]:
        return []


def test_get_stream_time_range_returns_utc_datetimes() -> None:
    client = StubClient(StubStream(time_range=[1_700_000_000_000, 1_700_000_060_000]))

    result = client.get_stream_time_range("bars")

    assert result.stream_key == "bars"
    assert result.start == datetime(2023, 11, 14, 22, 13, 20, tzinfo=timezone.utc)
    assert result.end == datetime(2023, 11, 14, 22, 14, 20, tzinfo=timezone.utc)


def test_get_stream_spaces_reports_unsupported_when_dxapi_returns_none() -> None:
    client = StubClient(StubStream(spaces=None))

    result = client.get_stream_spaces("bars")

    assert result.stream_key == "bars"
    assert result.spaces == []
    assert result.returned_count == 0
    assert result.supports_spaces is False


def test_get_stream_spaces_preserves_default_space_and_sorts() -> None:
    client = StubClient(StubStream(spaces=["blue", "", "red"]))

    result = client.get_stream_spaces("bars")

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

    result = client.get_stream_space_time_range("bars", "blue")

    assert result.stream_key == "bars"
    assert result.space == "blue"
    assert result.start == datetime(2023, 11, 14, 22, 13, 20, tzinfo=timezone.utc)
    assert result.end == datetime(2023, 11, 14, 22, 14, 20, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    "time_range",
    [[2, 1], [1, 2, 3]],
)
def test_get_stream_space_time_range_rejects_invalid_ranges(
    time_range: list[int],
) -> None:
    client = StubClient(StubStream(space_time_ranges={"blue": time_range}))

    with pytest.raises(InvalidStreamTimeRangeError):
        client.get_stream_space_time_range("bars", "blue")


def test_get_stream_messages_text_passes_space_to_reader() -> None:
    client = StubClient(StubStream(spaces=["blue"]))

    text = client.get_stream_messages_text("bars", reverse=True, count=1, space="blue")

    assert client.read_messages_calls == [(True, 1, "blue")]
    assert "Stream: bars" in text
    assert "Space: blue" in text
