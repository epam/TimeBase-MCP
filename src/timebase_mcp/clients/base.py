import base64
import json
import re
from abc import ABC, abstractmethod
from binascii import Error as BinasciiError
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import datetime, timezone
from types import TracebackType
from typing import Any, Literal

from timebase_mcp.errors import InvalidStreamTimeRangeError
from timebase_mcp.instance import TimeBaseInstanceConfig
from timebase_mcp.models import (
    CompileQQLResult,
    QQLErrorPosition,
    QQLFunctionsResult,
    StreamInfo,
    StreamSchema,
    StreamSpaces,
    StreamSpaceTimeRange,
    StreamSymbols,
    StreamTimeRange,
)
from timebase_mcp.qql_functions import normalize_qql_functions


class TimeBaseClient(AbstractContextManager["TimeBaseClient"], ABC):
    _DEFAULT_STREAM_SYMBOLS_PAGE_SIZE = 100
    _MAX_STREAM_SYMBOLS_PAGE_SIZE = 500
    _ERROR_CONTEXT_CHARS = 40
    _QQL_FUNCTIONS_LIMIT = 10_000
    _QQL_FUNCTION_SOURCE = {
        "stateless": "stateless_functions()",
        "stateful": "stateful_functions()",
    }

    def __init__(
        self,
        config: TimeBaseInstanceConfig,
        *,
        read_only: bool = False,
    ) -> None:
        self._read_only = read_only
        self._config = config

    def __enter__(self) -> "TimeBaseClient":
        self.open()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> Literal[False]:
        self.close()
        return False

    @abstractmethod
    def open(self) -> Any:
        """Opens a TimeBase connection."""

    @abstractmethod
    def close(self) -> None:
        """Closes the TimeBase connection."""

    def interrupt(self) -> None:
        """Interruption of an in-flight operation."""
        self.close()

    @abstractmethod
    def _require_db(self) -> Any:
        """Returns an open TimeBase connection."""

    @abstractmethod
    def get_stream(self, stream_key: str) -> Any:
        """Returns a stream by key or raises StreamNotFoundError."""

    @abstractmethod
    def _get_stream_schema_text(self, stream: Any) -> str:
        """Returns the text for a stream schema."""

    @abstractmethod
    def _list_stream_symbols(self, stream: Any) -> list[str]:
        """Returns stream symbols/entities."""

    @abstractmethod
    def _get_stream_time_range_ms(self, stream: Any) -> Any:
        """Returns the raw millisecond time range for a stream."""

    @abstractmethod
    def _list_stream_spaces(self, stream: Any) -> list[str] | None:
        """Returns stream spaces, or None if the stream does not support spaces."""

    @abstractmethod
    def _get_stream_space_time_range_ms(
        self,
        stream: Any,
        space: str,
    ) -> Any:
        """Returns the raw millisecond time range for a stream space."""

    @abstractmethod
    def _read_stream_messages(
        self,
        stream: Any,
        reverse: bool,
        count: int,
        space: str | None,
    ) -> list[dict[str, Any]]:
        """Read stream messages for preview output."""

    @abstractmethod
    def _read_query_messages(self, query_text: str, limit: int) -> list[dict[str, Any]]:
        """Read query messages for preview output."""

    @abstractmethod
    def _compile_query_tokens(self, query_text: str) -> list[Any]:
        """Compile QQL and return raw token objects."""

    def list_streams(self) -> list[StreamInfo]:
        streams = sorted(
            self._require_db().listStreams(),
            key=lambda stream: stream.key(),
        )
        return [
            StreamInfo(key=stream.key(), description=stream.description())
            for stream in streams
        ]

    def get_stream_schema(self, stream_key: str) -> StreamSchema:
        stream = self.get_stream(stream_key)
        return StreamSchema(
            stream_key=stream_key,
            schema_text=self._get_stream_schema_text(stream),
        )

    def get_stream_symbols(
        self,
        stream_key: str,
        limit: int = _DEFAULT_STREAM_SYMBOLS_PAGE_SIZE,
        cursor: str | None = None,
    ) -> StreamSymbols:
        if limit < 1:
            raise ValueError("limit must be at least 1.")

        page_size = min(limit, self._MAX_STREAM_SYMBOLS_PAGE_SIZE)
        offset, cursor_total_symbols = self._decode_stream_symbols_cursor(
            cursor, stream_key
        )
        stream = self.get_stream(stream_key)
        symbols = sorted(self._list_stream_symbols(stream))
        total_symbols = len(symbols)
        symbols_changed_since_cursor = (
            cursor is not None
            and cursor_total_symbols is not None
            and cursor_total_symbols != total_symbols
        )
        page_symbols = symbols[offset : offset + page_size]
        next_offset = offset + len(page_symbols)
        next_cursor = (
            self._encode_stream_symbols_cursor(
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

    def get_stream_time_range(self, stream_key: str) -> StreamTimeRange:
        stream = self.get_stream(stream_key)
        start, end = self._parse_time_range_ms(
            stream_key,
            self._get_stream_time_range_ms(stream),
        )

        return StreamTimeRange(
            stream_key=stream_key,
            start=start,
            end=end,
        )

    def get_stream_spaces(self, stream_key: str) -> StreamSpaces:
        stream = self.get_stream(stream_key)
        spaces = self._list_stream_spaces(stream)

        if spaces is None:
            return StreamSpaces(
                stream_key=stream_key,
                supports_spaces=False,
            )

        sorted_spaces = sorted(spaces)
        return StreamSpaces(
            stream_key=stream_key,
            spaces=sorted_spaces,
            returned_count=len(sorted_spaces),
            supports_spaces=True,
        )

    def get_stream_space_time_range(
        self,
        stream_key: str,
        space: str,
    ) -> StreamSpaceTimeRange:
        stream = self.get_stream(stream_key)
        time_range_ms = self._get_stream_space_time_range_ms(stream, space)
        start, end = self._parse_time_range_ms(stream_key, time_range_ms)

        return StreamSpaceTimeRange(
            stream_key=stream_key,
            space=space,
            start=start,
            end=end,
        )

    def get_stream_messages_text(
        self,
        stream_key: str,
        reverse: bool = False,
        count: int = 10,
        space: str | None = None,
    ) -> str:
        if count < 1:
            raise ValueError("count must be at least 1.")

        stream = self.get_stream(stream_key)
        messages = self._read_stream_messages(stream, reverse, count, space)

        return self._format_stream_messages_preview(
            stream_key=stream_key,
            reverse=reverse,
            count=count,
            space=space,
            messages=messages,
        )

    def execute_query(self, query: str, limit: int = 50) -> str:
        query_text = query.strip()
        if not query_text:
            raise ValueError("query must not be empty.")
        if limit < 1:
            raise ValueError("limit must be at least 1.")

        messages = self._read_query_messages(query_text, limit)
        return self._format_query_messages_preview(
            query_text=query_text,
            limit=limit,
            messages=messages,
        )

    def compile_query(self, query: str) -> CompileQQLResult:
        query_text = query.strip()
        if not query_text:
            raise ValueError("query must not be empty.")

        try:
            self._compile_query_tokens(query_text)
        except Exception as exc:
            error_text = str(exc)
            error_position = self._parse_compile_error_position(error_text)
            error_token, error_context = self._extract_error_details(
                query_text, error_position
            )
            return CompileQQLResult(
                valid=False,
                error=error_text,
                error_token=error_token,
                error_context=error_context,
                error_position=error_position,
            )

        return CompileQQLResult(valid=True)

    def list_qql_functions(
        self,
        kind: Literal["all", "stateless", "stateful"] = "all",
        function_id: str | None = None,
    ) -> QQLFunctionsResult:
        result = QQLFunctionsResult()
        selected_kinds = ("stateless", "stateful") if kind == "all" else (kind,)
        for selected_kind in selected_kinds:
            query_text = self._qql_functions_query(
                selected_kind,
                function_id=function_id,
            )
            messages = self._read_query_messages(query_text, self._QQL_FUNCTIONS_LIMIT)
            functions = normalize_qql_functions(selected_kind, messages)
            setattr(result, selected_kind, functions)

        result.function_count = len(result.stateless) + len(result.stateful)
        result.overload_count = sum(
            function.overload_count
            for function in [*result.stateless, *result.stateful]
        )
        return result

    @classmethod
    def _qql_functions_query(
        cls,
        kind: Literal["stateless", "stateful"],
        *,
        function_id: str | None,
    ) -> str:
        source = cls._QQL_FUNCTION_SOURCE[kind]
        if function_id is None:
            return f"SELECT {source} AS FUNCS"

        escaped_function_id = function_id.replace("'", "''")
        return (
            f"SELECT f AS FUNCS ARRAY JOIN {source} AS f "
            f"WHERE f.id == '{escaped_function_id}'"
        )

    def _normalize_message(self, message: Any) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "type": type(message).__name__,
            **self._message_payload(message),
        }

        timestamp = self._message_timestamp(message)
        if timestamp is not None:
            payload["timestamp"] = timestamp

        return payload

    @staticmethod
    def _message_payload(message: Any) -> dict[str, Any]:
        message_to_dict = getattr(message, "to_dict", None)
        if callable(message_to_dict):
            raw_payload = message_to_dict()
            if isinstance(raw_payload, dict):
                return {str(key): value for key, value in raw_payload.items()}

        return dict(vars(message))

    @staticmethod
    def _message_timestamp(message: Any) -> datetime | None:
        get_datetime = getattr(message, "getDateTime", None)
        if not callable(get_datetime):
            return None

        timestamp = get_datetime()
        if not isinstance(timestamp, datetime):
            return None

        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        return timestamp.astimezone(timezone.utc)

    def _format_stream_messages_preview(
        self,
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

        return self._format_messages_preview(
            header_lines=header_lines,
            messages=messages,
            empty_text="No messages found.",
        )

    def _format_query_messages_preview(
        self,
        query_text: str,
        limit: int,
        messages: list[dict[str, Any]],
    ) -> str:
        header_lines = [
            f"Query: {query_text}",
            f"Showing {len(messages)} of requested {limit} result rows",
        ]
        return self._format_messages_preview(
            header_lines=header_lines,
            messages=messages,
            empty_text="No result rows.",
        )

    def _format_messages_preview(
        self,
        header_lines: list[str],
        messages: list[dict[str, Any]],
        empty_text: str,
    ) -> str:
        if not messages:
            return "\n".join([*header_lines, "", empty_text])

        return "\n".join(
            [
                *header_lines,
                "",
                *[
                    f"{index}. {json.dumps(message, default=self._json_default, sort_keys=True)}"
                    for index, message in enumerate(messages, start=1)
                ],
            ]
        )

    @staticmethod
    def _json_default(value: Any) -> str:
        if isinstance(value, datetime):
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
            return value.astimezone(timezone.utc).isoformat()
        return str(value)

    @staticmethod
    def _parse_compile_error_position(error_text: str) -> QQLErrorPosition | None:
        range_match = re.search(
            r"\[at\s+(\d+)\.(\d+)\.\.(?:(\d+)\.)?(\d+)\]",
            error_text,
        )
        if range_match is not None:
            start_line = int(range_match.group(1))
            start_column = int(range_match.group(2))
            end_line = (
                int(range_match.group(3))
                if range_match.group(3) is not None
                else start_line
            )
            end_column = int(range_match.group(4))
            return QQLErrorPosition(
                start_line=start_line,
                start_column=start_column,
                end_line=end_line,
                end_column=end_column,
            )

        point_match = re.search(r"\[at\s+(\d+)[:.](\d+)\]", error_text)
        if point_match is None:
            return None

        line = int(point_match.group(1))
        column = int(point_match.group(2))
        return QQLErrorPosition(
            start_line=line,
            start_column=column,
            end_line=line,
            end_column=column,
        )

    @classmethod
    def _extract_error_details(
        cls,
        query_text: str,
        error_position: QQLErrorPosition | None,
    ) -> tuple[str | None, str | None]:
        if error_position is None:
            return None, None

        start_offset = cls._line_column_to_offset(
            query_text,
            error_position.start_line,
            error_position.start_column,
            is_end=False,
        )
        end_offset = cls._line_column_to_offset(
            query_text,
            error_position.end_line,
            error_position.end_column,
            is_end=True,
        )

        if start_offset is None or end_offset is None:
            return None, None

        if end_offset < start_offset:
            end_offset = start_offset

        error_token_value = query_text[start_offset:end_offset].strip()
        error_token = error_token_value or None
        context_start = max(0, start_offset - cls._ERROR_CONTEXT_CHARS)
        context_end = min(len(query_text), end_offset + cls._ERROR_CONTEXT_CHARS)
        context = query_text[context_start:context_end]
        if not context:
            return error_token, None
        if context_start > 0:
            context = f"...{context}"
        if context_end < len(query_text):
            context = f"{context}..."
        return error_token, context

    @staticmethod
    def _line_column_to_offset(
        text: str,
        line: int,
        column: int,
        *,
        is_end: bool,
    ) -> int | None:
        if line < 1 or column < 1:
            return None

        lines = text.splitlines(keepends=True)
        if line > len(lines):
            return None

        raw_line = lines[line - 1]
        line_without_newline = raw_line.rstrip("\r\n")
        line_start = sum(len(lines[index]) for index in range(line - 1))
        line_length = len(line_without_newline)

        if is_end:
            clamped_column = min(column, line_length)
            return line_start + clamped_column

        clamped_column = min(column - 1, line_length)
        return line_start + clamped_column

    @staticmethod
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

    @staticmethod
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

    @staticmethod
    def _timestamp_ms_to_datetime_utc(timestamp_ms: int) -> datetime:
        return datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)

    @classmethod
    def _parse_time_range_ms(
        cls,
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
            cls._timestamp_ms_to_datetime_utc(start_timestamp_ms),
            cls._timestamp_ms_to_datetime_utc(end_timestamp_ms),
        )

    @staticmethod
    def _closing(cursor: Any) -> AbstractContextManager[Any]:
        close = getattr(cursor, "close", None)
        if not callable(close):
            raise TypeError("Cursor object does not provide close().")

        class CursorContext(AbstractContextManager[Any]):
            def __enter__(self) -> Any:
                return cursor

            def __exit__(
                self,
                exc_type: type[BaseException] | None,
                exc: BaseException | None,
                tb: TracebackType | None,
            ) -> Literal[False]:
                close()
                return False

        return CursorContext()

    @staticmethod
    def _call_cursor_context(
        factory: Callable[..., Any],
        *args: Any,
        **kwargs: Any,
    ) -> AbstractContextManager[Any]:
        result = factory(*args, **kwargs)
        enter = getattr(result, "__enter__", None)
        exit_ = getattr(result, "__exit__", None)
        if callable(enter) and callable(exit_):
            return result
        return TimeBaseClient._closing(result)
