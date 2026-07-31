from __future__ import annotations

import re
from typing import Any, Literal

from timebase_mcp.clients.base import TimeBaseClient
from timebase_mcp.errors import ReadOnlyInstanceError
from timebase_mcp.models.core import (
    CompileQQLResult,
    QQLErrorPosition,
    QQLFunctionsResult,
)
from timebase_mcp.services.previews import format_messages_preview
from timebase_mcp.services.qql_functions import normalize_qql_functions

_ERROR_CONTEXT_CHARS = 40
_READ_ONLY_KEYWORD = "SELECT"
_KEYWORD_TOKEN_TYPE = "KEYWORD"
# QueryToken.location packs start line/column and end line/column into one int,
# 16 bits per field, lines and columns zero-based and the end exclusive.
_LOCATION_FIELD_MASK = 0xFFFF
_QQL_FUNCTIONS_LIMIT = 10_000
_QQL_FUNCTION_SOURCE = {
    "stateless": "stateless_functions()",
    "stateful": "stateful_functions()",
}


def execute_query(client: TimeBaseClient, query: str, limit: int = 50) -> str:
    query_text = query.strip()
    if not query_text:
        raise ValueError("query must not be empty.")
    if limit < 1:
        raise ValueError("limit must be at least 1.")

    if client.read_only:
        _reject_when_query_modifies(client, query_text)

    messages = client.read_query_messages(query_text, limit)
    client.raise_if_cancelled()
    return _format_query_messages_preview(
        query_text=query_text,
        limit=limit,
        messages=messages,
    )


def _reject_when_query_modifies(client: TimeBaseClient, query_text: str) -> None:
    keyword = _leading_keyword(client, query_text)
    if keyword == _READ_ONLY_KEYWORD:
        return

    statement = f"'{keyword}' statements are" if keyword else "This query is"
    raise ReadOnlyInstanceError(
        f"TimeBase instance '{client.instance_key}' is read-only. "
        f"{statement} rejected, only {_READ_ONLY_KEYWORD} queries are allowed."
    )


def _leading_keyword(client: TimeBaseClient, query_text: str) -> str | None:
    """First keyword of the compiled statement, or None when it cannot be read."""
    for token in client.compile_query_tokens(query_text):
        if getattr(token, "type", None) != _KEYWORD_TOKEN_TYPE:
            continue
        text = _token_text(query_text, token)
        return text.upper() if text is not None else None

    return None


def _token_text(query_text: str, token: Any) -> str | None:
    location = getattr(token, "location", None)
    if not isinstance(location, int):
        return None

    start_line = (location >> 48) & _LOCATION_FIELD_MASK
    start_column = (location >> 32) & _LOCATION_FIELD_MASK
    end_line = (location >> 16) & _LOCATION_FIELD_MASK
    end_column = location & _LOCATION_FIELD_MASK

    lines = query_text.splitlines()
    if start_line != end_line or start_line >= len(lines):
        return None

    text = lines[start_line][start_column:end_column]
    return text or None


def compile_query(client: TimeBaseClient, query: str) -> CompileQQLResult:
    query_text = query.strip()
    if not query_text:
        raise ValueError("query must not be empty.")

    try:
        client.compile_query_tokens(query_text)
    except Exception as exc:
        error_text = str(exc)
        error_position = _parse_compile_error_position(error_text)
        error_token, error_context = _extract_error_details(query_text, error_position)
        return CompileQQLResult(
            valid=False,
            error=error_text,
            error_token=error_token,
            error_context=error_context,
            error_position=error_position,
        )

    return CompileQQLResult(valid=True)


def list_qql_functions(
    client: TimeBaseClient,
    kind: Literal["all", "stateless", "stateful"] = "all",
    function_id: str | None = None,
) -> QQLFunctionsResult:
    result = QQLFunctionsResult()
    selected_kinds = ("stateless", "stateful") if kind == "all" else (kind,)
    for selected_kind in selected_kinds:
        client.raise_if_cancelled()
        query_text = _qql_functions_query(
            selected_kind,
            function_id=function_id,
        )
        messages = client.read_query_messages(query_text, _QQL_FUNCTIONS_LIMIT)
        client.raise_if_cancelled()
        functions = normalize_qql_functions(selected_kind, messages)
        setattr(result, selected_kind, functions)

    result.function_count = len(result.stateless) + len(result.stateful)
    result.overload_count = sum(
        function.overload_count for function in [*result.stateless, *result.stateful]
    )
    return result


def _qql_functions_query(
    kind: Literal["stateless", "stateful"],
    *,
    function_id: str | None,
) -> str:
    source = _QQL_FUNCTION_SOURCE[kind]
    if function_id is None:
        return f"SELECT {source} AS FUNCS"

    escaped_function_id = function_id.replace("'", "''")
    return (
        f"SELECT f AS FUNCS ARRAY JOIN {source} AS f "
        f"WHERE f.id == '{escaped_function_id}'"
    )


def _format_query_messages_preview(
    query_text: str,
    limit: int,
    messages: list[dict[str, Any]],
) -> str:
    header_lines = [
        f"Query: {query_text}",
        f"Showing {len(messages)} of requested {limit} result rows",
    ]
    return format_messages_preview(
        header_lines=header_lines,
        messages=messages,
        empty_text="No result rows.",
    )


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


def _extract_error_details(
    query_text: str,
    error_position: QQLErrorPosition | None,
) -> tuple[str | None, str | None]:
    if error_position is None:
        return None, None

    start_offset = _line_column_to_offset(
        query_text,
        error_position.start_line,
        error_position.start_column,
        is_end=False,
    )
    end_offset = _line_column_to_offset(
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
    context_start = max(0, start_offset - _ERROR_CONTEXT_CHARS)
    context_end = min(len(query_text), end_offset + _ERROR_CONTEXT_CHARS)
    context = query_text[context_start:context_end]
    if not context:
        return error_token, None
    if context_start > 0:
        context = f"...{context}"
    if context_end < len(query_text):
        context = f"{context}..."
    return error_token, context


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
