from __future__ import annotations

import base64
import json
from datetime import UTC, datetime
from typing import Any

import pytest
from typing_extensions import override

from tests.stubs import StubTimeBaseClient, stub_instance
from timebase_mcp.errors import StreamNotFoundError
from timebase_mcp.models.core import StreamInfo
from timebase_mcp.runtime.instance import TimeBaseInstanceRuntime
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


class StreamServiceStubClient(StubTimeBaseClient):
    def __init__(
        self, stream: StubStream, *, instance: TimeBaseInstanceRuntime | None = None
    ) -> None:
        super().__init__(instance or stub_instance())
        self.stream = stream
        self.read_messages_calls: list[tuple[bool, int, str | None]] = []
        self.symbol_calls: list[tuple[str, int, int]] = []

    @override
    def get_stream(self, stream_key: str) -> StubStream:
        assert stream_key == "bars"
        return self.stream

    @override
    def get_stream_schema_text(self, stream: Any) -> str:
        return "schema"

    @override
    def list_stream_symbols(
        self, stream_key: str, offset: int, limit: int
    ) -> tuple[int, list[str]]:
        self.symbol_calls.append((stream_key, offset, limit))
        symbols = self.stream.symbols
        return len(symbols), symbols[offset : offset + limit]

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
            datetime.fromtimestamp(start_ms / 1000, tz=UTC),
            datetime.fromtimestamp(end_ms / 1000, tz=UTC),
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
            datetime.fromtimestamp(start_ms / 1000, tz=UTC),
            datetime.fromtimestamp(end_ms / 1000, tz=UTC),
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

    @override
    def list_stream_symbols(
        self, stream_key: str, offset: int, limit: int
    ) -> tuple[int, list[str]]:
        raise StreamNotFoundError(stream_key)


class _CatalogStubClient(StubTimeBaseClient):
    def __init__(
        self,
        streams: list[StreamInfo],
        *,
        instance: TimeBaseInstanceRuntime | None = None,
    ) -> None:
        super().__init__(instance or stub_instance())
        self._streams = streams
        self.catalog_calls: list[tuple[int, int]] = []

    @override
    def list_stream_infos(
        self, offset: int, limit: int
    ) -> tuple[int, list[StreamInfo]]:
        self.catalog_calls.append((offset, limit))
        return len(self._streams), self._streams[offset : offset + limit]


def _legacy_cursor() -> str:
    payload = json.dumps(
        {"stream_key": "bars", "offset": 1, "total_symbols": 2}
    ).encode()
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _modified_cursor(cursor: str, **updates: object) -> str:
    payload = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
    payload.update(updates)
    return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")


def test_list_streams_preserves_native_order() -> None:
    client = _CatalogStubClient(
        [
            StreamInfo(key="zeta", description="z"),
            StreamInfo(key="alpha", description="a"),
            StreamInfo(key="mu", description=None),
        ]
    )

    result = stream_service.list_streams(client)

    assert [stream.key for stream in result.streams] == ["zeta", "alpha", "mu"]
    assert result.total_streams == result.returned_count == 3
    assert result.next_cursor is None
    assert client.catalog_calls == [(0, 100)]


def test_catalog_pagination_preserves_order_and_descriptions() -> None:
    streams = [StreamInfo(key=f"s{i:04d}", description=f"desc {i}") for i in range(600)]
    streams.extend(
        [
            StreamInfo(key="#events"),
            StreamInfo(key="metrics#"),
            StreamInfo(key="views#"),
        ]
    )
    streams.reverse()
    client = _CatalogStubClient(streams)
    first = stream_service.list_streams(client)
    assert first.returned_count == 100 and first.total_streams == 603
    assert first.next_cursor is not None
    fresh = _CatalogStubClient(streams)
    second = stream_service.list_streams(fresh, limit=1000, cursor=first.next_cursor)
    assert second.returned_count == 500 and second.next_cursor is not None
    last = stream_service.list_streams(fresh, cursor=second.next_cursor)
    assert last.returned_count == 3 and last.next_cursor is None
    assert first.streams + second.streams + last.streams == streams
    assert fresh.catalog_calls == [(100, 500), (600, 100)]
    assert (
        not first.streams_changed_since_cursor and not last.streams_changed_since_cursor
    )


def test_catalog_count_changes_and_offsets_past_end() -> None:
    client = _CatalogStubClient([StreamInfo(key="a"), StreamInfo(key="b")])
    first = stream_service.list_streams(client, limit=1)
    assert first.next_cursor is not None
    client._streams.clear()
    result = stream_service.list_streams(client, cursor=first.next_cursor)
    assert result.streams == [] and result.next_cursor is None
    assert result.streams_changed_since_cursor


def test_catalog_cursors_reject_other_tools_instances_and_versions() -> None:
    client = _CatalogStubClient([StreamInfo(key="a"), StreamInfo(key="b")])
    first = stream_service.list_streams(client, limit=1)
    assert first.next_cursor is not None
    with pytest.raises(ValueError, match="different stream or tool.*Restart"):
        stream_service.get_stream_symbols(client, "bars", cursor=first.next_cursor)
    other = _CatalogStubClient(client._streams, instance=stub_instance(key="other"))
    with pytest.raises(ValueError, match="different TimeBase instance"):
        stream_service.list_streams(other, cursor=first.next_cursor)
    assert other.catalog_calls == []
    symbols = StreamServiceStubClient(StubStream(symbols=["A", "B"]))
    symbol_page = stream_service.get_stream_symbols(symbols, "bars", limit=1)
    assert symbol_page.next_cursor is not None
    with pytest.raises(ValueError, match="different stream or tool.*Restart"):
        stream_service.list_streams(client, cursor=symbol_page.next_cursor)
    with pytest.raises(ValueError, match="Invalid cursor version.*Restart"):
        stream_service.list_streams(
            client, cursor=_modified_cursor(first.next_cursor, cursor_version=4)
        )
    assert client.catalog_calls == [(0, 1)]


@pytest.mark.parametrize("cursor", ["%%%", _legacy_cursor()])
def test_bad_catalog_cursors_are_rejected_before_reading(cursor: str) -> None:
    client = _CatalogStubClient([])
    with pytest.raises(ValueError):
        stream_service.list_streams(client, cursor=cursor)
    assert client.catalog_calls == []


def test_list_streams_rejects_non_positive_limit_before_reading() -> None:
    client = _CatalogStubClient([])
    with pytest.raises(ValueError, match="limit must be at least 1"):
        stream_service.list_streams(client, limit=0)
    assert client.catalog_calls == []


def test_catalog_rejects_out_of_range_offset_before_reading() -> None:
    client = _CatalogStubClient([StreamInfo(key="a"), StreamInfo(key="b")])
    first = stream_service.list_streams(client, limit=1)
    assert first.next_cursor is not None
    with pytest.raises(ValueError, match="Invalid cursor"):
        stream_service.list_streams(
            client, cursor=_modified_cursor(first.next_cursor, offset=2**40)
        )
    assert client.catalog_calls == [(0, 1)]


def test_catalog_resource_text_is_bounded_and_has_usable_tool_arguments() -> None:
    client = _CatalogStubClient([StreamInfo(key=f"s{i:03d}") for i in range(101)])
    text = stream_service.get_stream_catalog_text(client)
    assert "s099:" in text and "s100:" not in text
    args = json.loads(text.split("using arguments: ")[1])
    assert args["instance_key"] == client.instance_key
    last = stream_service.list_streams(client, cursor=args["cursor"])
    assert [s.key for s in last.streams] == ["s100"]
    assert (
        stream_service.get_stream_catalog_text(_CatalogStubClient([]))
        == "No streams found."
    )


def test_get_stream_schema_returns_schema_text() -> None:
    client = StreamServiceStubClient(StubStream())

    result = stream_service.get_stream_schema(client, "bars")

    assert result.stream_key == "bars"
    assert result.schema_text == "schema"


def test_get_stream_time_range_returns_utc_datetimes() -> None:
    client = StreamServiceStubClient(
        StubStream(time_range=[1_700_000_000_000, 1_700_000_060_000])
    )

    result = stream_service.get_stream_time_range(client, "bars")

    assert result.stream_key == "bars"
    assert result.start == datetime(2023, 11, 14, 22, 13, 20, tzinfo=UTC)
    assert result.end == datetime(2023, 11, 14, 22, 14, 20, tzinfo=UTC)


def test_get_stream_spaces_reports_unsupported_when_dxapi_returns_none() -> None:
    client = StreamServiceStubClient(StubStream(spaces=None))

    result = stream_service.get_stream_spaces(client, "bars")

    assert result.stream_key == "bars"
    assert result.spaces == []
    assert result.returned_count == 0
    assert result.supports_spaces is False


def test_get_stream_spaces_preserves_default_space_and_sorts() -> None:
    client = StreamServiceStubClient(StubStream(spaces=["blue", "", "red"]))

    result = stream_service.get_stream_spaces(client, "bars")

    assert result.spaces == ["", "blue", "red"]
    assert result.returned_count == 3
    assert result.supports_spaces is True


def test_get_stream_space_time_range_returns_utc_datetimes() -> None:
    client = StreamServiceStubClient(
        StubStream(
            space_time_ranges={
                "blue": [1_700_000_000_000, 1_700_000_060_000],
            },
        )
    )

    result = stream_service.get_stream_space_time_range(client, "bars", "blue")

    assert result.stream_key == "bars"
    assert result.space == "blue"
    assert result.start == datetime(2023, 11, 14, 22, 13, 20, tzinfo=UTC)
    assert result.end == datetime(2023, 11, 14, 22, 14, 20, tzinfo=UTC)


def test_get_stream_messages_text_passes_space_to_reader() -> None:
    client = StreamServiceStubClient(StubStream(spaces=["blue"]))

    text = stream_service.get_stream_messages_text(
        client, "bars", reverse=True, count=1, space="blue"
    )

    assert client.read_messages_calls == [(True, 1, "blue")]
    assert "Stream: bars" in text
    assert "Space: blue" in text


def test_get_stream_symbols_preserves_adapter_order_and_bounds_pages() -> None:
    client = StreamServiceStubClient(StubStream(symbols=["Z", "AA", "BBB"]))

    first = stream_service.get_stream_symbols(client, "bars", limit=2)

    assert first.symbols == ["Z", "AA"]
    assert first.returned_count == 2
    assert first.next_cursor is not None
    assert first.symbols_changed_since_cursor is False

    second = stream_service.get_stream_symbols(
        client, "bars", limit=2, cursor=first.next_cursor
    )
    assert second.symbols == ["BBB"]
    assert second.returned_count == 1
    assert second.next_cursor is None
    assert client.symbol_calls == [("bars", 0, 2), ("bars", 2, 2)]


def test_get_stream_symbols_rejects_non_positive_limit() -> None:
    client = StreamServiceStubClient(StubStream(symbols=["a"]))

    with pytest.raises(ValueError, match="limit must be at least 1"):
        stream_service.get_stream_symbols(client, "bars", limit=0)


def test_get_stream_symbols_caps_page_size_at_500() -> None:
    symbols = [f"s{index:04d}" for index in range(600)]
    client = StreamServiceStubClient(StubStream(symbols=symbols))

    result = stream_service.get_stream_symbols(client, "bars", limit=1000)

    assert result.returned_count == 500
    assert len(result.symbols) == 500
    assert result.next_cursor is not None
    assert client.symbol_calls == [("bars", 0, 500)]


def test_symbol_cursors_reject_other_streams_before_reading() -> None:
    client = StreamServiceStubClient(StubStream(symbols=["a", "b"]))
    first = stream_service.get_stream_symbols(client, "bars", limit=1)
    assert first.next_cursor is not None
    other_stream_cursor = _modified_cursor(first.next_cursor, stream_key="other")
    with pytest.raises(ValueError, match="Invalid cursor"):
        stream_service.get_stream_symbols(client, "bars", cursor=other_stream_cursor)
    assert client.symbol_calls == [("bars", 0, 1)]


def test_old_symbol_cursors_require_restarting_before_reading() -> None:
    client = StreamServiceStubClient(StubStream(symbols=["A", "B"]))
    cursor = _legacy_cursor()
    with pytest.raises(ValueError, match="Invalid cursor.*Restart"):
        stream_service.get_stream_symbols(client, "bars", cursor=cursor)
    assert client.symbol_calls == []


def test_symbol_cursors_are_bound_to_mcp_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = StreamServiceStubClient(StubStream(symbols=["A", "B"]))
    first = stream_service.get_stream_symbols(client, "bars", limit=1)
    assert first.next_cursor is not None
    monkeypatch.setattr(stream_service, "_MCP_VERSION", "next-version")
    with pytest.raises(ValueError, match="Invalid cursor version.*Restart"):
        stream_service.get_stream_symbols(client, "bars", cursor=first.next_cursor)
    assert client.symbol_calls == [("bars", 0, 1)]


def test_symbol_cursors_reject_other_instances() -> None:
    original = StreamServiceStubClient(StubStream(symbols=["A", "B"]))
    first = stream_service.get_stream_symbols(original, "bars", limit=1)
    assert first.next_cursor is not None
    other = StreamServiceStubClient(
        original.stream,
        instance=stub_instance(key="other"),
    )
    with pytest.raises(ValueError, match="different TimeBase instance.*Restart"):
        stream_service.get_stream_symbols(other, "bars", cursor=first.next_cursor)
    assert other.symbol_calls == []


@pytest.mark.parametrize("payload", [[], None, "text", True, 12])
def test_non_object_cursor_payloads_are_invalid(payload: object) -> None:
    cursor = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()
    client = StreamServiceStubClient(StubStream())
    with pytest.raises(ValueError, match="Invalid cursor"):
        stream_service.get_stream_symbols(client, "bars", cursor=cursor)
    assert client.symbol_calls == []


@pytest.mark.parametrize(
    "updates",
    [
        {"offset": True},
        {"offset": -1},
        {"offset": 2**40},
        {"total": True},
        {"total": None},
        {"total": -1},
    ],
)
def test_invalid_versioned_cursor_bounds_are_rejected(
    updates: dict[str, object],
) -> None:
    client = StreamServiceStubClient(StubStream(symbols=["A", "B"]))
    first = stream_service.get_stream_symbols(client, "bars", limit=1)
    assert first.next_cursor is not None
    with pytest.raises(ValueError, match="Invalid cursor"):
        stream_service.get_stream_symbols(
            client, "bars", cursor=_modified_cursor(first.next_cursor, **updates)
        )
    assert client.symbol_calls == [("bars", 0, 1)]


def test_get_stream_symbols_reports_count_changes() -> None:
    stream = StubStream(symbols=["z", "a", "m"])
    client = StreamServiceStubClient(stream)
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
