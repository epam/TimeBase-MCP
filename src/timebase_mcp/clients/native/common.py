from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from contextlib import closing as _closing
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from timebase_mcp.config.types import Edition
from timebase_mcp.errors import InvalidStreamTimeRangeError, StreamNotFoundError
from timebase_mcp.models.core import StreamInfo
from timebase_mcp.runtime.instance import TimeBaseInstanceRuntime

STREAMS_QUERY = (
    "WITH streams() AS 'raw', "
    "raw[range(LO, min(HI, size(raw)))] AS 'selected' "
    "SELECT size(raw) AS 'total', selected.key AS 'keys', "
    "selected.description AS 'descriptions'"
)
SYMBOLS_QUERY = (
    "WITH symbols(SK) AS 'raw' SELECT size(raw) AS 'total', "
    "sort(raw)[range(LO, min(HI, size(raw)))] AS 'symbols'"
)


class _StreamsResult(BaseModel):
    total: int = Field(ge=0)
    keys: list[str] | None = None
    descriptions: list[str | None] | None = None


class _StreamSymbolsResult(BaseModel):
    total: int = Field(ge=0)
    symbols: list[str] | None = None


def closing(cursor: Any) -> AbstractContextManager[Any]:
    if not callable(getattr(cursor, "close", None)):
        raise TypeError("Cursor object does not provide close().")
    return _closing(cursor)


def call_cursor_context(
    factory: Callable[..., Any],
    *args: Any,
    **kwargs: Any,
) -> AbstractContextManager[Any]:
    result = factory(*args, **kwargs)
    enter = getattr(result, "__enter__", None)
    exit_ = getattr(result, "__exit__", None)
    if callable(enter) and callable(exit_):
        return result
    return closing(result)


def normalize_message(message: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "type": type(message).__name__,
        **message_payload(message),
    }

    timestamp = message_timestamp(message)
    if timestamp is not None:
        payload["timestamp"] = timestamp

    return payload


def message_payload(message: Any) -> dict[str, Any]:
    message_to_dict = getattr(message, "to_dict", None)
    if callable(message_to_dict):
        raw_payload = message_to_dict()
        if isinstance(raw_payload, dict):
            return {str(key): value for key, value in raw_payload.items()}

    return dict(vars(message))


def read_stream_infos(
    db: Any,
    offset: int,
    limit: int,
    parameter_factory: Callable[[str, str, str], Any],
    *,
    check_cancelled: Callable[[], None],
) -> tuple[int, list[StreamInfo]]:
    _validate_metadata_bounds(offset, limit)
    check_cancelled()
    with call_cursor_context(
        db.executeQuery,
        STREAMS_QUERY,
        params=[
            parameter_factory("LO", "INTEGER", str(offset)),
            parameter_factory("HI", "INTEGER", str(offset + limit)),
        ],
    ) as cursor:
        has_result = cursor.next()
        check_cancelled()
        if not has_result:
            raise ValueError("QQL stream query returned no result.")

        result = _StreamsResult.model_validate(
            message_payload(cursor.getMessage()), strict=True
        )
        keys = result.keys or []
        descriptions = result.descriptions or []
        expected_count = min(limit, max(0, result.total - offset))
        if len(keys) != expected_count or len(descriptions) != expected_count:
            raise ValueError("QQL returned an unexpected number of streams.")

        streams = [
            StreamInfo(key=key, description=description)
            for key, description in zip(keys, descriptions, strict=True)
        ]
        check_cancelled()
        return result.total, streams


def _validate_metadata_bounds(offset: int, limit: int) -> None:
    if (
        type(offset) is not int
        or type(limit) is not int
        or not 1 <= limit <= 500
        or not 0 <= offset <= 2**31 - 1 - limit
    ):
        raise ValueError("Invalid metadata bounds.")


def read_stream_symbols(
    db: Any,
    stream_key: str,
    offset: int,
    limit: int,
    parameter_factory: Callable[[str, str, str], Any],
    *,
    check_cancelled: Callable[[], None],
) -> tuple[int, list[str]]:
    _validate_metadata_bounds(offset, limit)
    check_cancelled()

    with call_cursor_context(
        db.executeQuery,
        SYMBOLS_QUERY,
        params=[
            parameter_factory("SK", "VARCHAR", stream_key),
            parameter_factory("LO", "INTEGER", str(offset)),
            parameter_factory("HI", "INTEGER", str(offset + limit)),
        ],
    ) as cursor:
        has_result = cursor.next()
        check_cancelled()
        if not has_result:
            raise ValueError("QQL symbol query returned no result.")

        payload = message_payload(cursor.getMessage())
        if payload.get("total") is None:
            raise StreamNotFoundError(stream_key)

        result = _StreamSymbolsResult.model_validate(payload, strict=True)

        symbols = result.symbols or []
        if len(symbols) != min(limit, max(0, result.total - offset)):
            raise ValueError("QQL returned an unexpected number of symbols.")

        check_cancelled()
        return result.total, symbols


def message_timestamp(message: Any) -> datetime | None:
    get_datetime = getattr(message, "getDateTime", None)
    if not callable(get_datetime):
        return None

    timestamp = get_datetime()
    if not isinstance(timestamp, datetime):
        return None

    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    return timestamp.astimezone(UTC)


def timestamp_ms_to_datetime_utc(timestamp_ms: int) -> datetime:
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=UTC)


def parse_time_range_ms(
    stream_key: str,
    time_range_ms: Any,
) -> tuple[datetime | None, datetime | None]:
    if not time_range_ms:
        return None, None

    if len(time_range_ms) != 2:
        raise InvalidStreamTimeRangeError(stream_key, time_range_ms)

    start_timestamp_ms = time_range_ms[0]
    end_timestamp_ms = time_range_ms[1]

    if start_timestamp_ms > end_timestamp_ms:
        raise InvalidStreamTimeRangeError(stream_key, time_range_ms)

    return (
        timestamp_ms_to_datetime_utc(start_timestamp_ms),
        timestamp_ms_to_datetime_utc(end_timestamp_ms),
    )


def connection_error_hint(
    instance: TimeBaseInstanceRuntime,
    exc: Exception,
    *,
    edition: Edition,
) -> str:
    message = str(exc)
    normalized = message.casefold()
    hints: list[str] = []

    if "certificate verification" in normalized or "ssl" in normalized:
        hints.append(
            "For TLS/certificate issues, use DXAPI_SSL_CERT_FILE with a DER "
            "certificate, or DXAPI_SSL_TRUST_ALL=true for non-production testing."
        )

    if "timed out" in normalized or "timeout" in normalized:
        if edition == "enterprise":
            hints.append(
                "If this TimeBase endpoint is behind an HTTPS/TLS terminator, "
                "set DXAPI_SSL_TERMINATION=true or let local auto auth discover "
                "the HTTPS /tb/oauthinfo endpoint before connecting."
            )
        else:
            hints.append(
                "If this TimeBase endpoint is behind an HTTPS/TLS terminator, "
                "set DXAPI_SSL_TERMINATION=true."
            )

    if "wrong username or password" in normalized and instance.config.auth_mode in (
        "auto",
        "none",
    ):
        if edition == "enterprise":
            hints.append(
                "The server looks protected but MCP connected without credentials. "
                "For local MCP, use URL-only auto auth or set "
                "TIMEBASE_AUTH_MODE=interactive. For remote MCP, configure "
                "forward_identity or a service account."
            )
        else:
            hints.append(
                "The server looks protected but MCP connected without credentials. "
                "Interactive OAuth requires the enterprise dxapi client."
            )

    if instance.config.auto_auth_error:
        hints.append(
            f"OAuth auto-discovery failed earlier: {instance.config.auto_auth_error}"
        )

    if not hints:
        return ""
    return " " + " ".join(hints)
