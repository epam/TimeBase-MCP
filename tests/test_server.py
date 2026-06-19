from collections.abc import AsyncGenerator, Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
import logging

import pytest
from inline_snapshot import snapshot
from mcp.client.session import ClientSession
from mcp.shared.exceptions import McpError
from mcp.shared.memory import create_connected_server_and_client_session
from mcp.types import TextContent, TextResourceContents
from pydantic import AnyUrl, SecretStr, TypeAdapter

from timebase_mcp import resources as resources_module
from timebase_mcp.clients import factory as client_factory
from timebase_mcp.config import MCPSettings, SettingsEnv
from timebase_mcp.errors import (
    TimeBaseOperationError,
    TimeBaseOperationLimitError,
    TimeBaseOperationTimeoutError,
)
from timebase_mcp.models import StreamInfo
from timebase_mcp.server import create_server
from timebase_mcp.tools import queries as query_tools
from timebase_mcp.tools import streams as stream_tools


@dataclass
class _StubStream:
    key: str
    description: str | None = None


@dataclass
class _StubSchema:
    schema_text: str


_RESOURCE_URI_ADAPTER = TypeAdapter(AnyUrl)


def _resource_uri(value: str) -> AnyUrl:
    return _RESOURCE_URI_ADAPTER.validate_python(value)


def test_remote_unauthenticated_bind_logs_warning(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv(SettingsEnv.MCP_TRANSPORT, "streamable-http")
    monkeypatch.setenv(SettingsEnv.MCP_HOST, "0.0.0.0")

    with caplog.at_level(logging.WARNING):
        create_server(MCPSettings())

    assert any(
        "unauthenticated HTTP MCP server" in record.message for record in caplog.records
    )


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
            "list_timebase_instances",
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
            "list_timebase_instances": {
                "readOnlyHint": True,
                "openWorldHint": False,
            },
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
    assert "instance_key" in tools_result.tools[2].inputSchema["properties"]
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
async def test_read_resources_return_expected_text(
    monkeypatch: pytest.MonkeyPatch,
    client_session_factory: Callable[
        [MCPSettings | None],
        AbstractAsyncContextManager[ClientSession],
    ],
) -> None:
    async def run_resource(_ctx, operation):
        class StubClient:
            def list_streams(self) -> list[_StubStream]:
                return [_StubStream("bars", "desc")]

            def get_stream_schema(self, stream_key: str) -> _StubSchema:
                return _StubSchema(f"schema:{stream_key}")

        return operation(StubClient())

    monkeypatch.setattr(resources_module, "run_with_context", run_resource)

    async with client_session_factory(None) as client_session:
        catalog = await client_session.read_resource(
            _resource_uri("timebase://streams")
        )
        schema = await client_session.read_resource(
            _resource_uri("timebase://streams/bars/schema")
        )

    catalog_text = [
        content.text
        for content in catalog.contents
        if isinstance(content, TextResourceContents)
    ]
    schema_text = [
        content.text
        for content in schema.contents
        if isinstance(content, TextResourceContents)
    ]

    assert catalog_text == ["bars: desc"]
    assert schema_text == ["schema:bars"]


@pytest.mark.anyio
async def test_read_resource_surfaces_operation_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fail_resource(_ctx, _operation):
        raise TimeBaseOperationError("resource failed")

    monkeypatch.setattr(resources_module, "run_with_context", fail_resource)

    server = create_server(MCPSettings())
    async with create_connected_server_and_client_session(
        server,
        raise_exceptions=False,
    ) as client_session:
        with pytest.raises(
            McpError,
            match=r"Error reading resource timebase://streams: resource failed",
        ):
            await client_session.read_resource(_resource_uri("timebase://streams"))


@pytest.mark.anyio
async def test_call_list_timebase_instances_tool(
    client_session_factory: Callable[
        [MCPSettings | None],
        AbstractAsyncContextManager[ClientSession],
    ],
) -> None:
    settings = MCPSettings.model_validate(
        {
            "servers": [
                {
                    "name": "prod",
                    "description": "Production TimeBase",
                    "url": "dxtick://prod:8011",
                },
                {"url": "dxtick://dev:8011"},
            ],
        }
    )

    async with client_session_factory(settings) as client_session:
        result = await client_session.call_tool("list_timebase_instances", {})

    assert result.isError is False
    assert result.structuredContent == {
        "result": [
            {
                "name": "prod",
                "description": "Production TimeBase",
                "is_default": True,
            },
            {
                "name": "dxtick://dev:8011",
                "description": None,
                "is_default": False,
            },
        ]
    }


@pytest.mark.anyio
async def test_call_stream_tool_uses_selected_instance(
    monkeypatch: pytest.MonkeyPatch,
    client_session_factory: Callable[
        [MCPSettings | None],
        AbstractAsyncContextManager[ClientSession],
    ],
) -> None:
    selected_instances: list[str | None] = []

    async def run_list_streams(_ctx, _operation, *, instance_key=None):
        selected_instances.append(instance_key)
        return [StreamInfo(key="bars", description=f"from {instance_key}")]

    monkeypatch.setattr(stream_tools, "run_with_context", run_list_streams)
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

    assert result.isError is False
    assert selected_instances == ["dev"]
    assert result.structuredContent == {
        "result": [{"key": "bars", "description": "from dev"}]
    }


@pytest.mark.anyio
async def test_call_stream_tool_uses_default_instance_when_omitted(
    monkeypatch: pytest.MonkeyPatch,
    client_session_factory: Callable[
        [MCPSettings | None],
        AbstractAsyncContextManager[ClientSession],
    ],
) -> None:
    selected_instances: list[str | None] = []

    async def run_list_streams(_ctx, _operation, *, instance_key=None):
        selected_instances.append(instance_key)
        return []

    monkeypatch.setattr(stream_tools, "run_with_context", run_list_streams)

    async with client_session_factory(None) as client_session:
        result = await client_session.call_tool("list_streams", {})

    assert result.isError is False
    assert selected_instances == [None]


@pytest.mark.anyio
async def test_call_get_server_configuration_tool(
    monkeypatch: pytest.MonkeyPatch,
    client_session_factory: Callable[
        [MCPSettings | None],
        AbstractAsyncContextManager[ClientSession],
    ],
) -> None:
    monkeypatch.delenv("DXAPI_SSL_TERMINATION", raising=False)
    monkeypatch.delenv("DXAPI_SSL_TRUST_ALL", raising=False)
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
            '  "edition": null,\n'
            '  "inbound_auth_enabled": false,\n'
            '  "outbound_auth_mode": "auto",\n'
            '  "principal": null,\n'
            '  "tb_http_urls": [\n'
            '    "http://localhost:8011",\n'
            '    "https://localhost:8011"\n'
            "  ],\n"
            '  "oauth_redirect_uri": "http://127.0.0.1:8000/",\n'
            '  "dxapi_ssl_termination": false,\n'
            '  "dxapi_ssl_trust_all": false\n'
            "}"
        )
    ]
    assert result.structuredContent == {
        "transport": "stdio",
        "tb_url": "dxtick://localhost:8011",
        "tb_username": None,
        "edition": None,
        "inbound_auth_enabled": False,
        "outbound_auth_mode": "auto",
        "principal": None,
        "tb_http_urls": ["http://localhost:8011", "https://localhost:8011"],
        "oauth_redirect_uri": "http://127.0.0.1:8000/",
        "dxapi_ssl_termination": False,
        "dxapi_ssl_trust_all": False,
    }
    assert result.isError is False


@pytest.mark.anyio
async def test_call_get_server_configuration_tool_reports_detected_edition(
    client_session_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DXAPI_SSL_TERMINATION", raising=False)
    monkeypatch.delenv("DXAPI_SSL_TRUST_ALL", raising=False)
    settings = MCPSettings()
    settings.set_detected_edition("community")

    async with client_session_factory(settings) as client_session:
        result = await client_session.call_tool("get_server_configuration", {})

    assert result.structuredContent == {
        "transport": "stdio",
        "tb_url": "dxtick://localhost:8011",
        "tb_username": None,
        "edition": "community",
        "inbound_auth_enabled": False,
        "outbound_auth_mode": "auto",
        "principal": None,
        "tb_http_urls": ["http://localhost:8011", "https://localhost:8011"],
        "oauth_redirect_uri": "http://127.0.0.1:8000/",
        "dxapi_ssl_termination": False,
        "dxapi_ssl_trust_all": False,
    }


@pytest.mark.anyio
async def test_call_get_server_configuration_tool_reports_enterprise_for_oauth2(
    client_session_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DXAPI_SSL_TERMINATION", raising=False)
    monkeypatch.delenv("DXAPI_SSL_TRUST_ALL", raising=False)
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
        "inbound_auth_enabled": False,
        "outbound_auth_mode": "oauth2_client_credentials",
        "principal": None,
        "tb_http_urls": ["http://localhost:8011", "https://localhost:8011"],
        "oauth_redirect_uri": "http://127.0.0.1:8000/",
        "dxapi_ssl_termination": False,
        "dxapi_ssl_trust_all": False,
    }


@pytest.mark.anyio
async def test_call_get_server_configuration_tool_sanitizes_url_credentials(
    client_session_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DXAPI_SSL_TERMINATION", raising=False)
    monkeypatch.delenv("DXAPI_SSL_TRUST_ALL", raising=False)
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
        "inbound_auth_enabled": False,
        "outbound_auth_mode": "basic",
        "principal": None,
        "tb_http_urls": [
            "http://timebase.example:8011",
            "https://timebase.example:8011",
        ],
        "oauth_redirect_uri": "http://127.0.0.1:8000/",
        "dxapi_ssl_termination": False,
        "dxapi_ssl_trust_all": False,
    }


@pytest.mark.anyio
async def test_call_compile_query_tool_returns_compact_success_payload(
    monkeypatch: pytest.MonkeyPatch,
    client_session_factory: Callable[
        [MCPSettings | None],
        AbstractAsyncContextManager[ClientSession],
    ],
) -> None:
    async def run_compile_query(_ctx, _operation, *, instance_key=None):
        return {
            "valid": True,
            "error": None,
            "error_token": None,
            "error_context": None,
            "error_position": None,
        }

    monkeypatch.setattr(
        query_tools,
        "run_with_context",
        run_compile_query,
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
    async def fail_operation(_ctx, _operation, *, instance_key=None):
        raise error_type(message)

    monkeypatch.setattr(query_tools, "run_with_context", fail_operation)

    server = create_server(MCPSettings())
    async with create_connected_server_and_client_session(
        server,
        raise_exceptions=False,
    ) as client_session:
        result = await client_session.call_tool(
            "execute_query",
            {"query": 'select * from "bars"'},
        )

    text_content = [
        content.text for content in result.content if isinstance(content, TextContent)
    ]

    assert result.isError is True
    assert result.structuredContent is None
    assert text_content == [f"Error executing tool execute_query: {message}"]


@pytest.mark.anyio
async def test_call_compile_query_tool_returns_structured_error_payload(
    monkeypatch: pytest.MonkeyPatch,
    client_session_factory: Callable[
        [MCPSettings | None],
        AbstractAsyncContextManager[ClientSession],
    ],
) -> None:
    async def run_compile_query(_ctx, _operation, *, instance_key=None):
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
        "run_with_context",
        run_compile_query,
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
