from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import datetime, timezone
from types import TracebackType
from typing import Any, Literal
from typing_extensions import override

from timebase_mcp.config.types import Edition
from timebase_mcp.errors import InvalidStreamTimeRangeError
from timebase_mcp.runtime.instance import TimeBaseInstanceRuntime


def closing(cursor: Any) -> AbstractContextManager[Any]:
    close = getattr(cursor, "close", None)
    if not callable(close):
        raise TypeError("Cursor object does not provide close().")

    class CursorContext(AbstractContextManager[Any]):
        @override
        def __enter__(self) -> Any:
            return cursor

        @override
        def __exit__(
            self,
            exc_type: type[BaseException] | None,
            exc: BaseException | None,
            tb: TracebackType | None,
        ) -> Literal[False]:
            close()
            return False

    return CursorContext()


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


def message_timestamp(message: Any) -> datetime | None:
    get_datetime = getattr(message, "getDateTime", None)
    if not callable(get_datetime):
        return None

    timestamp = get_datetime()
    if not isinstance(timestamp, datetime):
        return None

    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return timestamp.astimezone(timezone.utc)


def timestamp_ms_to_datetime_utc(timestamp_ms: int) -> datetime:
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)


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
