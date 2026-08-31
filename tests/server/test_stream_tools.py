from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager

import pytest
from mcp.client import Client
from mcp_types import TextContent

from timebase_mcp.config.settings import MCPSettings
from timebase_mcp.models.core import StreamInfo
from timebase_mcp.server import create_server
from timebase_mcp.tools import streams as stream_tools

from tests.server.helpers import (
    SpaceToolClient,
)


@pytest.mark.anyio
async def test_call_stream_tool_uses_selected_instance(
    monkeypatch: pytest.MonkeyPatch,
    client_session_factory: Callable[
        [MCPSettings | None],
        AbstractAsyncContextManager[Client],
    ],
) -> None:
    selected_instances: list[str | None] = []

    async def run_list_streams(
        _ctx, _operation, *, instance_key=None, report_progress=False
    ):
        selected_instances.append(instance_key)
        return [StreamInfo(key="bars", description=f"from {instance_key}")]

    monkeypatch.setattr(stream_tools, "run_tool_operation", run_list_streams)
    settings = MCPSettings.model_validate(
        {
            "servers": [
                {"name": "prod", "url": "dxtick://prod:8011"},
                {"name": "dev", "url": "dxtick://dev:8011"},
            ]
        }
    )

    async with client_session_factory(settings) as client_session:
        result = await client_session.call_tool(
            "list_streams",
            {"instance_key": "dev"},
        )

    assert result.is_error is False
    assert selected_instances == ["dev"]
    assert result.structured_content == {
        "result": [{"key": "bars", "description": "from dev"}]
    }


@pytest.mark.anyio
async def test_call_stream_tool_uses_single_instance_when_key_is_omitted(
    monkeypatch: pytest.MonkeyPatch,
    client_session_factory: Callable[
        [MCPSettings | None],
        AbstractAsyncContextManager[Client],
    ],
) -> None:
    selected_instances: list[str | None] = []

    async def run_list_streams(
        _ctx, _operation, *, instance_key=None, report_progress=False
    ):
        selected_instances.append(instance_key)
        return []

    monkeypatch.setattr(stream_tools, "run_tool_operation", run_list_streams)

    async with client_session_factory(None) as client_session:
        result = await client_session.call_tool("list_streams", {})

    assert result.is_error is False
    assert selected_instances == [None]


@pytest.mark.anyio
async def test_call_stream_space_tools_pass_arguments(
    monkeypatch: pytest.MonkeyPatch,
    client_session_factory: Callable[
        [MCPSettings | None],
        AbstractAsyncContextManager[Client],
    ],
) -> None:
    selected_instances: list[str | None] = []
    calls: list[tuple[str, str, str | None]] = []

    async def run_stream_operation(
        _ctx, operation, *, instance_key=None, report_progress=False
    ):
        selected_instances.append(instance_key)
        return operation(SpaceToolClient(calls))

    monkeypatch.setattr(stream_tools, "run_tool_operation", run_stream_operation)

    async with client_session_factory(None) as client_session:
        spaces_result = await client_session.call_tool(
            "list_stream_spaces",
            {"stream_key": "bars", "instance_key": "dev"},
        )
        range_result = await client_session.call_tool(
            "get_stream_space_time_range",
            {"stream_key": "bars", "space": "blue", "instance_key": "dev"},
        )
        messages_result = await client_session.call_tool(
            "get_stream_messages",
            {
                "stream_key": "bars",
                "space": "blue",
                "reverse": True,
                "count": 3,
                "instance_key": "dev",
            },
        )

    assert spaces_result.is_error is False
    assert spaces_result.structured_content == {
        "stream_key": "bars",
        "spaces": ["", "blue"],
        "returned_count": 2,
        "supports_spaces": True,
    }
    assert range_result.is_error is False
    assert range_result.structured_content == {
        "stream_key": "bars",
        "space": "blue",
        "start": None,
        "end": None,
    }
    assert messages_result.is_error is False
    assert selected_instances == ["dev", "dev", "dev"]
    assert calls == [
        ("spaces", "bars", None),
        ("space_range", "bars", "blue"),
        ("messages", "bars", "blue"),
    ]


@pytest.mark.anyio
async def test_call_stream_tool_requires_instance_key_when_multiple_instances() -> None:
    settings = MCPSettings.model_validate(
        {
            "servers": [
                {"name": "prod", "url": "dxtick://prod:8011"},
                {"name": "dev", "url": "dxtick://dev:8011"},
            ]
        }
    )
    server = create_server(settings)

    async with Client(server, raise_exceptions=False) as client_session:
        result = await client_session.call_tool("list_streams", {})

    text_content = [
        content.text for content in result.content if isinstance(content, TextContent)
    ]

    assert result.is_error is True
    assert result.structured_content is None
    assert text_content == [
        "Error executing tool list_streams: "
        "instance_key is required when multiple TimeBase instances are configured. "
        "Call list_timebase_instances to choose an instance."
    ]
