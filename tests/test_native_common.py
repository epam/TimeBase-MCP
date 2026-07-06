from __future__ import annotations

from datetime import datetime, timezone
from typing import cast

import pytest

from timebase_mcp.clients.native.common import (
    call_cursor_context,
    closing,
    connection_error_hint,
    message_payload,
    message_timestamp,
    normalize_message,
    parse_time_range_ms,
)
from timebase_mcp.errors import InvalidStreamTimeRangeError
from timebase_mcp.runtime.instance import (
    TimeBaseInstanceConfig,
    TimeBaseInstanceRuntime,
)


class _ContextManagerCursor:
    def __init__(self, value: str) -> None:
        self.value = value
        self.closed = False

    def __enter__(self) -> str:
        return self.value

    def __exit__(self, *_args: object) -> None:
        self.closed = True


class _CloseOnlyCursor:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class _MessageWithToDict:
    def to_dict(self) -> dict[str, object]:
        return {"symbol": "AAPL", "price": 10.5}

    def getDateTime(self) -> datetime:
        return datetime(2024, 1, 2, 3, 4, 5, tzinfo=timezone.utc)


class _MessageWithVars:
    def __init__(self) -> None:
        self.symbol = "MSFT"

    def getDateTime(self) -> datetime:
        return datetime(2024, 2, 3, 4, 5, 6)


def test_call_cursor_context_uses_native_context_manager() -> None:
    cursor = _ContextManagerCursor("payload")

    with call_cursor_context(lambda: cursor) as opened:
        assert opened == "payload"

    assert cursor.closed is True


def test_call_cursor_context_wraps_close_only_cursor() -> None:
    cursor = _CloseOnlyCursor()

    with call_cursor_context(lambda: cursor) as opened:
        assert opened is cursor

    assert cursor.closed is True


def test_closing_requires_close_method() -> None:
    with pytest.raises(TypeError, match="close"):
        closing(object())


def test_normalize_message_prefers_to_dict() -> None:
    message = _MessageWithToDict()

    payload = normalize_message(message)

    assert payload["type"] == "_MessageWithToDict"
    assert payload["symbol"] == "AAPL"
    assert payload["timestamp"] == datetime(2024, 1, 2, 3, 4, 5, tzinfo=timezone.utc)


def test_normalize_message_falls_back_to_vars() -> None:
    message = _MessageWithVars()

    payload = normalize_message(message)

    assert payload["type"] == "_MessageWithVars"
    assert payload["symbol"] == "MSFT"
    assert payload["timestamp"] == datetime(2024, 2, 3, 4, 5, 6, tzinfo=timezone.utc)


def test_message_payload_and_timestamp_handle_missing_get_datetime() -> None:
    class PlainMessage:
        def __init__(self) -> None:
            self.symbol = "IBM"

    message = PlainMessage()

    assert message_payload(message) == {"symbol": "IBM"}
    assert message_timestamp(message) is None


def test_parse_time_range_ms_returns_none_for_empty_range() -> None:
    assert parse_time_range_ms("bars", None) == (None, None)
    assert parse_time_range_ms("bars", []) == (None, None)


def test_parse_time_range_ms_converts_valid_millisecond_range() -> None:
    start, end = parse_time_range_ms("bars", [1_700_000_000_000, 1_700_000_060_000])

    assert start == datetime(2023, 11, 14, 22, 13, 20, tzinfo=timezone.utc)
    assert end == datetime(2023, 11, 14, 22, 14, 20, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    "time_range",
    [[2, 1], [1, 2, 3]],
)
def test_parse_time_range_ms_rejects_invalid_ranges(time_range: list[int]) -> None:
    with pytest.raises(InvalidStreamTimeRangeError):
        parse_time_range_ms("bars", time_range)


def _runtime(
    *, auth_mode: str = "auto", auto_auth_error: str | None = None
) -> TimeBaseInstanceRuntime:
    from timebase_mcp.config.types import OutboundAuthMode

    return TimeBaseInstanceRuntime(
        key="default",
        config=TimeBaseInstanceConfig(
            tb_url="dxtick://tb.example.com:8011",
            auth_mode=cast(OutboundAuthMode, auth_mode),
            auto_auth_error=auto_auth_error,
        ),
    )


def test_connection_error_hint_enterprise_includes_interactive_guidance() -> None:
    hint = connection_error_hint(
        _runtime(),
        Exception("Handshake failed: Wrong username or password"),
        edition="enterprise",
    )

    assert "TIMEBASE_AUTH_MODE=interactive" in hint
    assert "/tb/oauthinfo" not in hint


def test_connection_error_hint_enterprise_timeout_mentions_oauth_discovery() -> None:
    hint = connection_error_hint(
        _runtime(),
        Exception("Connection timed out"),
        edition="enterprise",
    )

    assert "DXAPI_SSL_TERMINATION=true" in hint
    assert "/tb/oauthinfo" in hint


def test_connection_error_hint_community_mentions_enterprise_client_for_oauth() -> None:
    hint = connection_error_hint(
        _runtime(),
        Exception("Handshake failed: Wrong username or password"),
        edition="community",
    )

    assert "enterprise dxapi client" in hint
    assert "TIMEBASE_AUTH_MODE=interactive" not in hint


def test_connection_error_hint_includes_auto_auth_error() -> None:
    hint = connection_error_hint(
        _runtime(auto_auth_error="Failed to fetch TimeBase OAuth metadata."),
        Exception("Handshake failed: Wrong username or password"),
        edition="enterprise",
    )

    assert "OAuth auto-discovery failed earlier" in hint
