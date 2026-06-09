from collections.abc import AsyncGenerator, Callable
from contextlib import AbstractAsyncContextManager

import pytest
from inline_snapshot import snapshot
from mcp.client.session import ClientSession
from mcp.shared.memory import create_connected_server_and_client_session
from mcp.types import TextContent
from pydantic import SecretStr

from timebase_mcp.clients import factory as client_factory
from timebase_mcp.config import MCPSettings
from timebase_mcp.server import create_server
from timebase_mcp.tools import queries as query_tools


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def client_session_factory() -> Callable[
    [MCPSettings | None],
    AbstractAsyncContextManager[ClientSession],
]:
    def build(
        settings: MCPSettings | None = None,
    ) -> AbstractAsyncContextManager[ClientSession]:
        server = create_server(settings or MCPSettings())
        return create_connected_server_and_client_session(
            server,
            raise_exceptions=True,
        )

    return build


@pytest.fixture
async def client_session(
    client_session_factory: Callable[
        [MCPSettings | None],
        AbstractAsyncContextManager[ClientSession],
    ],
) -> AsyncGenerator[ClientSession]:
    async with client_session_factory(None) as session:
        yield session


@pytest.mark.anyio
async def test_list_tools_resources_and_templates(
    client_session: ClientSession,
) -> None:
    tools_result = await client_session.list_tools()
    resources_result = await client_session.list_resources()
    templates_result = await client_session.list_resource_templates()

    assert [tool.name for tool in tools_result.tools] == snapshot(
        [
            "get_server_configuration",
            "list_streams",
            "get_stream_schema",
            "get_stream_time_range",
            "get_stream_symbols",
            "get_stream_messages",
            "execute_query",
            "compile_query",
        ]
    )
    assert {
        tool.name: {
            "readOnlyHint": None
            if tool.annotations is None
            else tool.annotations.readOnlyHint,
            "openWorldHint": None
            if tool.annotations is None
            else tool.annotations.openWorldHint,
        }
        for tool in tools_result.tools
    } == snapshot(
        {
            "get_server_configuration": {
                "readOnlyHint": True,
                "openWorldHint": False,
            },
            "list_streams": {
                "readOnlyHint": True,
                "openWorldHint": True,
            },
            "get_stream_schema": {
                "readOnlyHint": True,
                "openWorldHint": True,
            },
            "get_stream_time_range": {
                "readOnlyHint": True,
                "openWorldHint": True,
            },
            "get_stream_symbols": {
                "readOnlyHint": True,
                "openWorldHint": True,
            },
            "get_stream_messages": {"readOnlyHint": True, "openWorldHint": True},
            "execute_query": {"readOnlyHint": False, "openWorldHint": True},
            "compile_query": {"readOnlyHint": True, "openWorldHint": True},
        }
    )
    assert [resource.name for resource in resources_result.resources] == snapshot(
        ["stream_catalog"]
    )
    assert [
        template.name for template in templates_result.resourceTemplates
    ] == snapshot(["stream_schema"])
    assert [
        template.uriTemplate for template in templates_result.resourceTemplates
    ] == snapshot(["timebase://streams/{stream_key}/schema"])


@pytest.mark.anyio
async def test_call_get_server_configuration_tool(
    monkeypatch: pytest.MonkeyPatch,
    client_session_factory: Callable[
        [MCPSettings | None],
        AbstractAsyncContextManager[ClientSession],
    ],
) -> None:
    monkeypatch.setattr(
        client_factory,
        "_available_editions",
        lambda _statuses=None: ("enterprise", "community"),
    )

    async with client_session_factory(None) as client_session:
        result = await client_session.call_tool("get_server_configuration", {})

    text_content = [
        content.text for content in result.content if isinstance(content, TextContent)
    ]

    assert text_content == [
        (
            "{\n"
            '  "transport": "stdio",\n'
            '  "tb_url": "dxtick://localhost:8011",\n'
            '  "tb_username": null,\n'
            '  "edition": null\n'
            "}"
        )
    ]
    assert result.structuredContent == {
        "transport": "stdio",
        "tb_url": "dxtick://localhost:8011",
        "tb_username": None,
        "edition": None,
    }
    assert result.isError is False


@pytest.mark.anyio
async def test_call_get_server_configuration_tool_reports_detected_edition(
    client_session_factory,
) -> None:
    settings = MCPSettings()
    settings.set_detected_edition("community")

    async with client_session_factory(settings) as client_session:
        result = await client_session.call_tool("get_server_configuration", {})

    assert result.structuredContent == {
        "transport": "stdio",
        "tb_url": "dxtick://localhost:8011",
        "tb_username": None,
        "edition": "community",
    }


@pytest.mark.anyio
async def test_call_get_server_configuration_tool_reports_enterprise_for_oauth2(
    client_session_factory,
) -> None:
    settings = MCPSettings(
        tb_username="service-user",
        tb_oauth2_token_url="https://idp.example/token",
        tb_oauth2_client_id="client-id",
        tb_oauth2_client_secret=SecretStr("client-secret"),
    )

    async with client_session_factory(settings) as client_session:
        result = await client_session.call_tool("get_server_configuration", {})

    assert result.structuredContent == {
        "transport": "stdio",
        "tb_url": "dxtick://localhost:8011",
        "tb_username": "service-user",
        "edition": "enterprise",
    }


@pytest.mark.anyio
async def test_call_get_server_configuration_tool_sanitizes_url_credentials(
    client_session_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(client_factory, "_available_editions", lambda: ())

    settings = MCPSettings(
        tb_url="dxtick://user:pass@timebase.example:8011",
    )

    async with client_session_factory(settings) as client_session:
        result = await client_session.call_tool("get_server_configuration", {})

    assert result.structuredContent == {
        "transport": "stdio",
        "tb_url": "dxtick://timebase.example:8011",
        "tb_username": "user",
        "edition": None,
    }


@pytest.mark.anyio
async def test_call_compile_query_tool_returns_compact_success_payload(
    monkeypatch: pytest.MonkeyPatch,
    client_session_factory: Callable[
        [MCPSettings | None],
        AbstractAsyncContextManager[ClientSession],
    ],
) -> None:
    monkeypatch.setattr(
        query_tools,
        "run_with_client",
        lambda settings, operation, read_only: {
            "valid": True,
            "error": None,
            "error_token": None,
            "error_context": None,
            "error_position": None,
        },
    )

    async with client_session_factory(None) as client_session:
        result = await client_session.call_tool(
            "compile_query",
            {"query": 'select * from "bars"'},
        )

    assert result.isError is False
    assert result.structuredContent == {
        "valid": True,
        "error": None,
        "error_token": None,
        "error_context": None,
        "error_position": None,
    }


@pytest.mark.anyio
async def test_call_compile_query_tool_returns_structured_error_payload(
    monkeypatch: pytest.MonkeyPatch,
    client_session_factory: Callable[
        [MCPSettings | None],
        AbstractAsyncContextManager[ClientSession],
    ],
) -> None:
    monkeypatch.setattr(
        query_tools,
        "run_with_client",
        lambda settings, operation, read_only: {
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
        },
    )

    async with client_session_factory(None) as client_session:
        result = await client_session.call_tool(
            "compile_query",
            {"query": 'select * from "bars"'},
        )

    assert result.isError is False
    assert result.structuredContent == {
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
