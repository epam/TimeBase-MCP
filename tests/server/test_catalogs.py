from __future__ import annotations

import pytest
from inline_snapshot import snapshot
from mcp.client import Client

from tests.server.helpers import (
    LOCAL_TOOL_NAMES,
)
from timebase_mcp.config.settings import MCPSettings
from timebase_mcp.server import create_server


@pytest.mark.parametrize(
    ("mode", "protocol_version"),
    [
        ("auto", "2026-07-28"),
        ("legacy", "2025-11-25"),
    ],
)
@pytest.mark.anyio
async def test_supported_protocol_versions(
    mode: str,
    protocol_version: str,
) -> None:
    async with Client(create_server(MCPSettings()), mode=mode) as client_session:
        await client_session.list_tools()

        assert client_session.protocol_version == protocol_version


@pytest.mark.anyio
async def test_list_tools_resources_and_templates(
    client_session: Client,
) -> None:
    tools_result = await client_session.list_tools()
    resources_result = await client_session.list_resources()
    templates_result = await client_session.list_resource_templates()

    assert [tool.name for tool in tools_result.tools] == snapshot(
        [
            "list_timebase_instances",
            "get_server_configuration",
            "get_timebase_status",
            "list_timebase_activity",
            "get_timebase_activity_detail",
            "list_streams",
            "get_stream_schema",
            "get_stream_time_range",
            "list_stream_spaces",
            "get_stream_space_time_range",
            "get_stream_symbols",
            "get_stream_messages",
            "execute_query",
            "compile_query",
            "list_qql_functions",
        ]
    )
    for tool in tools_result.tools:
        assert tool.annotations is not None
        if tool.name == "execute_query":
            assert tool.annotations.read_only_hint is False
            assert tool.annotations.destructive_hint is True
            assert tool.annotations.idempotent_hint is False
        else:
            assert tool.annotations.read_only_hint is True
        assert tool.annotations.open_world_hint is (tool.name not in LOCAL_TOOL_NAMES)
    assert "instance_key" not in tools_result.tools[1].input_schema["properties"]
    assert "instance_key" in tools_result.tools[2].input_schema["properties"]
    assert [resource.name for resource in resources_result.resources] == snapshot(
        ["stream_catalog"]
    )
    assert [
        template.name for template in templates_result.resource_templates
    ] == snapshot(
        ["stream_schema", "instance_stream_catalog", "instance_stream_schema"]
    )
    assert [
        template.uri_template for template in templates_result.resource_templates
    ] == snapshot(
        [
            "timebase://streams/{stream_key}/schema",
            "timebase://instances/{instance_key}/streams",
            "timebase://instances/{instance_key}/streams/{stream_key}/schema",
        ]
    )
