from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager

import pytest
from mcp.client import Client
from mcp_types import TextContent

from timebase_mcp.config.settings import MCPSettings
from timebase_mcp.errors import (
    TimeBaseOperationError,
    TimeBaseOperationLimitError,
    TimeBaseOperationTimeoutError,
)
from timebase_mcp.server import create_server
from timebase_mcp.tools import queries as query_tools


@pytest.mark.anyio
async def test_call_compile_query_tool_returns_compact_success_payload(
    monkeypatch: pytest.MonkeyPatch,
    client_session_factory: Callable[
        [MCPSettings | None],
        AbstractAsyncContextManager[Client],
    ],
) -> None:
    async def run_compile_query(
        _ctx, _operation, *, instance_key=None, report_progress=False
    ):
        return {
            "valid": True,
            "error": None,
            "error_token": None,
            "error_context": None,
            "error_position": None,
        }

    monkeypatch.setattr(
        query_tools,
        "run_tool_operation",
        run_compile_query,
    )

    async with client_session_factory(None) as client_session:
        result = await client_session.call_tool(
            "compile_query",
            {"query": 'select * from "bars"'},
        )

    assert result.is_error is False
    assert result.structured_content == {
        "valid": True,
        "error": None,
        "error_token": None,
        "error_context": None,
        "error_position": None,
    }


@pytest.mark.anyio
async def test_call_list_qql_functions_tool_returns_structured_payload(
    monkeypatch: pytest.MonkeyPatch,
    client_session_factory: Callable[
        [MCPSettings | None],
        AbstractAsyncContextManager[Client],
    ],
) -> None:
    selected_instances: list[str | None] = []
    selected_kinds: list[str] = []
    selected_function_ids: list[str | None] = []

    async def run_list_qql_functions(
        _ctx, operation, *, instance_key=None, report_progress=False
    ):
        selected_instances.append(instance_key)
        return operation(object())

    def list_qql_functions(client, kind: str, function_id: str | None = None):
        selected_kinds.append(kind)
        selected_function_ids.append(function_id)
        return {
            "stateless": [
                {
                    "id": "MAX",
                    "signatures": [
                        "MAX(x: INTEGER(INT64), y: INTEGER(INT64)) -> INTEGER(INT64)?"
                    ],
                    "overload_count": 1,
                }
            ],
            "stateful": [],
            "function_count": 1,
            "overload_count": 1,
        }

    monkeypatch.setattr(
        query_tools,
        "run_tool_operation",
        run_list_qql_functions,
    )
    monkeypatch.setattr(
        query_tools.query_service,
        "list_qql_functions",
        list_qql_functions,
    )

    async with client_session_factory(None) as client_session:
        result = await client_session.call_tool(
            "list_qql_functions",
            {"instance_key": "dev", "kind": "stateless", "function_id": "MAX"},
        )

    assert result.is_error is False
    assert selected_instances == ["dev"]
    assert selected_kinds == ["stateless"]
    assert selected_function_ids == ["MAX"]
    assert result.structured_content == {
        "stateless": [
            {
                "id": "MAX",
                "signatures": [
                    "MAX(x: INTEGER(INT64), y: INTEGER(INT64)) -> INTEGER(INT64)?"
                ],
                "overload_count": 1,
            }
        ],
        "stateful": [],
        "function_count": 1,
        "overload_count": 1,
    }


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("error_type", "message"),
    [
        (
            TimeBaseOperationLimitError,
            "Maximum concurrent TimeBase operations reached.",
        ),
        (
            TimeBaseOperationError,
            "Database is open in read-only mode",
        ),
        (
            TimeBaseOperationTimeoutError,
            "TimeBase operation timed out after 1 seconds.",
        ),
    ],
)
async def test_call_execute_query_tool_surfaces_operation_errors_to_client(
    monkeypatch: pytest.MonkeyPatch,
    error_type: type[Exception],
    message: str,
) -> None:
    async def fail_operation(
        _ctx, _operation, *, instance_key=None, report_progress=False
    ):
        raise error_type(message)

    monkeypatch.setattr(
        "timebase_mcp.tools.common.run_with_context",
        fail_operation,
    )

    server = create_server(MCPSettings())
    async with Client(server, raise_exceptions=False) as client_session:
        result = await client_session.call_tool(
            "execute_query",
            {"query": 'select * from "bars"'},
        )

    text_content = [
        content.text for content in result.content if isinstance(content, TextContent)
    ]

    assert result.is_error is True
    assert result.structured_content is None
    assert text_content == [f"Error executing tool execute_query: {message}"]


@pytest.mark.anyio
async def test_call_compile_query_tool_returns_structured_error_payload(
    monkeypatch: pytest.MonkeyPatch,
    client_session_factory: Callable[
        [MCPSettings | None],
        AbstractAsyncContextManager[Client],
    ],
) -> None:
    async def run_compile_query(
        _ctx, _operation, *, instance_key=None, report_progress=False
    ):
        return {
            "valid": False,
            "error": "QQL compile error [at 6.7..12].",
            "error_token": '"low"',
            "error_context": '..."high" FLOAT\\n      "low" FLOAT,...',
            "error_position": {
                "start_line": 6,
                "start_column": 7,
                "end_line": 6,
                "end_column": 12,
            },
        }

    monkeypatch.setattr(
        query_tools,
        "run_tool_operation",
        run_compile_query,
    )

    async with client_session_factory(None) as client_session:
        result = await client_session.call_tool(
            "compile_query",
            {"query": 'select * from "bars"'},
        )

    assert result.is_error is False
    assert result.structured_content == {
        "valid": False,
        "error": "QQL compile error [at 6.7..12].",
        "error_token": '"low"',
        "error_context": '..."high" FLOAT\\n      "low" FLOAT,...',
        "error_position": {
            "start_line": 6,
            "start_column": 7,
            "end_line": 6,
            "end_column": 12,
        },
    }


@pytest.mark.anyio
async def test_call_list_qql_functions_rejects_non_identifier_function_id(
    monkeypatch: pytest.MonkeyPatch,
    client_session_factory: Callable[
        [MCPSettings | None],
        AbstractAsyncContextManager[Client],
    ],
) -> None:
    executed = False

    def list_qql_functions(client, kind: str, function_id: str | None = None):
        nonlocal executed
        executed = True
        return {}

    monkeypatch.setattr(
        query_tools.query_service, "list_qql_functions", list_qql_functions
    )

    async with client_session_factory(None) as client_session:
        result = await client_session.call_tool(
            "list_qql_functions",
            {"function_id": "MAX' OR '1'='1"},
        )

    assert result.is_error is True
    assert executed is False
