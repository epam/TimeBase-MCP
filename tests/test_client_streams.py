from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from typing_extensions import override

from tests.stubs import StubTimeBaseClient, stub_instance
from timebase_mcp.services import streams as stream_service


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
