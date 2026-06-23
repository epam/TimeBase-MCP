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
    assert "instance_key" not in tools_result.tools[1].inputSchema["properties"]
    assert "instance_key" in tools_result.tools[2].inputSchema["properties"]
    assert [resource.name for resource in resources_result.resources] == snapshot(
        ["stream_catalog"]
    )
    assert [
        template.name for template in templates_result.resourceTemplates
    ] == snapshot(
        ["stream_schema", "instance_stream_catalog", "instance_stream_schema"]
    )
    assert [
        template.uriTemplate for template in templates_result.resourceTemplates
    ] == snapshot(
        [
            "timebase://streams/{stream_key}/schema",
            "timebase://instances/{instance_key}/streams",
            "timebase://instances/{instance_key}/streams/{stream_key}/schema",
        ]
    )


@pytest.mark.anyio
async def test_read_resources_return_expected_text(
    monkeypatch: pytest.MonkeyPatch,
    client_session_factory: Callable[
        [MCPSettings | None],
        AbstractAsyncContextManager[ClientSession],
    ],
) -> None:
    selected_instances: list[str | None] = []

    async def run_resource(_ctx, operation, *, instance_key=None):
        selected_instances.append(instance_key)

        class StubClient:
            def list_streams(self) -> list[_StubStream]:
                return [_StubStream("bars", f"desc:{instance_key}")]

            def get_stream_schema(self, stream_key: str) -> _StubSchema:
                return _StubSchema(f"schema:{instance_key}:{stream_key}")

        return operation(StubClient())

    monkeypatch.setattr(resources_module, "run_with_context", run_resource)

    async with client_session_factory(None) as client_session:
        catalog = await client_session.read_resource(
            _resource_uri("timebase://streams")
        )
        schema = await client_session.read_resource(
            _resource_uri("timebase://streams/bars/schema")
        )
        instance_catalog = await client_session.read_resource(
            _resource_uri("timebase://instances/dev/streams")
        )
        instance_schema = await client_session.read_resource(
            _resource_uri("timebase://instances/dev/streams/bars/schema")
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
    instance_catalog_text = [
        content.text
        for content in instance_catalog.contents
        if isinstance(content, TextResourceContents)
    ]
    instance_schema_text = [
        content.text
        for content in instance_schema.contents
        if isinstance(content, TextResourceContents)
    ]

    assert selected_instances == [None, None, "dev", "dev"]
    assert catalog_text == ["bars: desc:None"]
    assert schema_text == ["schema:None:bars"]
    assert instance_catalog_text == ["bars: desc:dev"]
    assert instance_schema_text == ["schema:dev:bars"]


@pytest.mark.anyio
async def test_read_resource_surfaces_operation_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fail_resource(_ctx, _operation, *, instance_key=None):
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
async def test_read_unscoped_resource_requires_instance_key_when_multiple_instances() -> (
    None
):
    settings = MCPSettings.model_validate(
        {
            "servers": [
                {"name": "prod", "url": "dxtick://prod:8011"},
                {"name": "dev", "url": "dxtick://dev:8011"},
            ]
        }
    )
    server = create_server(settings)

    async with create_connected_server_and_client_session(
        server,
        raise_exceptions=False,
    ) as client_session:
        with pytest.raises(
            McpError,
            match=(
                r"Error reading resource timebase://streams: "
                r"instance_key is required when multiple TimeBase instances are configured"
            ),
        ):
            await client_session.read_resource(_resource_uri("timebase://streams"))


@pytest.mark.anyio
async def test_read_instance_scoped_resource_uses_selected_instance_when_multiple_instances(
    monkeypatch: pytest.MonkeyPatch,
    client_session_factory: Callable[
        [MCPSettings | None],
        AbstractAsyncContextManager[ClientSession],
    ],
) -> None:
    selected_instances: list[str | None] = []

    async def run_resource(_ctx, operation, *, instance_key=None):
        selected_instances.append(instance_key)

        class StubClient:
            def list_streams(self) -> list[_StubStream]:
                return [_StubStream("bars", f"from {instance_key}")]

        return operation(StubClient())

    monkeypatch.setattr(resources_module, "run_with_context", run_resource)
    settings = MCPSettings.model_validate(
        {
            "servers": [
                {"name": "prod", "url": "dxtick://prod:8011"},
                {"name": "dev", "url": "dxtick://dev:8011"},
            ]
        }
    )

    async with client_session_factory(settings) as client_session:
        catalog = await client_session.read_resource(
            _resource_uri("timebase://instances/dev/streams")
        )

    catalog_text = [
        content.text
        for content in catalog.contents
        if isinstance(content, TextResourceContents)
    ]

    assert selected_instances == ["dev"]
    assert catalog_text == ["bars: from dev"]


@pytest.mark.anyio
async def test_read_instance_scoped_resource_supports_url_instance_key(
    monkeypatch: pytest.MonkeyPatch,
    client_session_factory: Callable[
        [MCPSettings | None],
        AbstractAsyncContextManager[ClientSession],
    ],
) -> None:
    selected_instances: list[str | None] = []

    async def run_resource(_ctx, operation, *, instance_key=None):
        selected_instances.append(instance_key)

        class StubClient:
            def list_streams(self) -> list[_StubStream]:
                return [_StubStream("bars", f"from {instance_key}")]

        return operation(StubClient())

    monkeypatch.setattr(resources_module, "run_with_context", run_resource)
    settings = MCPSettings.model_validate(
        {
            "servers": [
                {"name": "prod", "url": "dxtick://prod:8011"},
                {"url": "dxtick://dev:8011"},
            ]
        }
    )

    async with client_session_factory(settings) as client_session:
        catalog = await client_session.read_resource(
            _resource_uri("timebase://instances/dxtick%3A%2F%2Fdev%3A8011/streams")
        )

    catalog_text = [
        content.text
        for content in catalog.contents
        if isinstance(content, TextResourceContents)
    ]

    assert selected_instances == ["dxtick://dev:8011"]
    assert catalog_text == ["bars: from dxtick://dev:8011"]


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
            },
            {
                "name": "dxtick://dev:8011",
                "description": None,
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

    async with create_connected_server_and_client_session(
        server,
        raise_exceptions=False,
    ) as client_session:
        result = await client_session.call_tool("list_streams", {})

    text_content = [
        content.text for content in result.content if isinstance(content, TextContent)
    ]

    assert result.isError is True
    assert result.structuredContent is None
    assert text_content == [
        "Error executing tool list_streams: "
        "instance_key is required when multiple TimeBase instances are configured. "
        "Call list_timebase_instances to choose an instance."
    ]


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
            '  "inbound_auth_mode": "none",\n'
            '  "principal": null,\n'
            '  "oauth_redirect_uri": "http://127.0.0.1:8000/",\n'
            '  "timebase_instances": [\n'
            "    {\n"
            '      "name": "default",\n'
            '      "description": null,\n'
            '      "url": "dxtick://localhost:8011",\n'
            '      "username": null,\n'
            '      "edition": null,\n'
            '      "outbound_auth_mode": "auto",\n'
            '      "http_url": null,\n'
            '      "dxapi_ssl_termination": false,\n'
            '      "dxapi_ssl_trust_all": false\n'
            "    }\n"
            "  ]\n"
            "}"
        )
    ]
    assert result.structuredContent == {
        "transport": "stdio",
        "inbound_auth_mode": "none",
        "principal": None,
        "oauth_redirect_uri": "http://127.0.0.1:8000/",
        "timebase_instances": [
            {
                "name": "default",
                "description": None,
                "url": "dxtick://localhost:8011",
                "username": None,
                "edition": None,
                "outbound_auth_mode": "auto",
                "http_url": None,
                "dxapi_ssl_termination": False,
                "dxapi_ssl_trust_all": False,
            }
        ],
    }
    assert result.isError is False


@pytest.mark.anyio
async def test_call_get_server_configuration_reports_all_timebase_instances(
    monkeypatch: pytest.MonkeyPatch,
    client_session_factory: Callable[
        [MCPSettings | None],
        AbstractAsyncContextManager[ClientSession],
    ],
) -> None:
    monkeypatch.delenv("DXAPI_SSL_TERMINATION", raising=False)
    monkeypatch.delenv("DXAPI_SSL_TRUST_ALL", raising=False)
    monkeypatch.setattr(client_factory, "_available_editions", lambda: ())
    settings = MCPSettings.model_validate(
        {
            "servers": [
                {
                    "name": "prod",
                    "description": "Production TimeBase",
                    "url": "dxtick://prod:8011",
                    "http_base_url": "https://prod.example/tb",
                },
                {"name": "dev", "url": "dxtick://dev:8012"},
            ]
        }
    )

    async with client_session_factory(settings) as client_session:
        result = await client_session.call_tool("get_server_configuration", {})

    assert result.isError is False
    structured_content = result.structuredContent
    assert structured_content is not None
    assert structured_content["timebase_instances"] == [
        {
            "name": "prod",
            "description": "Production TimeBase",
            "url": "dxtick://prod:8011",
            "username": None,
            "edition": None,
            "outbound_auth_mode": "auto",
            "http_url": "https://prod.example/tb",
            "dxapi_ssl_termination": False,
            "dxapi_ssl_trust_all": False,
        },
        {
            "name": "dev",
            "description": None,
            "url": "dxtick://dev:8012",
            "username": None,
            "edition": None,
            "outbound_auth_mode": "auto",
            "http_url": None,
            "dxapi_ssl_termination": False,
            "dxapi_ssl_trust_all": False,
        },
    ]


@pytest.mark.anyio
async def test_call_get_server_configuration_reports_inbound_auth_mode() -> None:
    settings = MCPSettings(
        transport="streamable-http",
        auth_audience="timebase-api",
    )
    runtime = build_runtime(settings)

    configuration = build_server_configuration(runtime)

    assert configuration.inbound_auth_mode == "jwt"


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
        "inbound_auth_mode": "none",
        "principal": None,
        "oauth_redirect_uri": "http://127.0.0.1:8000/",
        "timebase_instances": [
            {
                "name": "default",
                "description": None,
                "url": "dxtick://localhost:8011",
                "username": None,
                "edition": "community",
                "outbound_auth_mode": "auto",
                "http_url": None,
                "dxapi_ssl_termination": False,
                "dxapi_ssl_trust_all": False,
            }
        ],
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
        "inbound_auth_mode": "none",
        "principal": None,
        "oauth_redirect_uri": "http://127.0.0.1:8000/",
        "timebase_instances": [
            {
                "name": "default",
                "description": None,
                "url": "dxtick://localhost:8011",
                "username": "service-user",
                "edition": "enterprise",
                "outbound_auth_mode": "oauth2_client_credentials",
                "http_url": None,
                "dxapi_ssl_termination": False,
                "dxapi_ssl_trust_all": False,
            }
        ],
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
        "inbound_auth_mode": "none",
        "principal": None,
        "oauth_redirect_uri": "http://127.0.0.1:8000/",
        "timebase_instances": [
            {
                "name": "default",
                "description": None,
                "url": "dxtick://timebase.example:8011",
                "username": "user",
                "edition": None,
                "outbound_auth_mode": "basic",
                "http_url": None,
                "dxapi_ssl_termination": False,
                "dxapi_ssl_trust_all": False,
            }
        ],
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
