import logging
from collections.abc import AsyncGenerator, Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass

import httpx2
import pytest
from inline_snapshot import snapshot
from mcp.client import Client
from mcp.shared.exceptions import MCPError
from mcp_types import TextContent, TextResourceContents
from pydantic import SecretStr

from timebase_mcp import resources as resources_module
from timebase_mcp.clients import factory as client_factory
from timebase_mcp.config.env import SettingsEnv
from timebase_mcp.config.settings import MCPSettings
from timebase_mcp.errors import (
    TimeBaseOperationError,
    TimeBaseOperationLimitError,
    TimeBaseOperationTimeoutError,
)
from timebase_mcp.models.core import StreamInfo
from timebase_mcp.runtime.introspection import build_server_configuration
from timebase_mcp.runtime.state import build_runtime
from timebase_mcp.server import create_server
from timebase_mcp.tools import queries as query_tools
from timebase_mcp.tools import streams as stream_tools
from timebase_mcp.version import get_version


@dataclass
class _StubStream:
    key: str
    description: str | None = None


def _resource_text(result) -> list[str]:
    return [
        content.text
        for content in result.contents
        if isinstance(content, TextResourceContents)
    ]


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
    AbstractAsyncContextManager[Client],
]:
    def build(
        settings: MCPSettings | None = None,
    ) -> AbstractAsyncContextManager[Client]:
        server = create_server(settings or MCPSettings())
        return Client(server, raise_exceptions=True)

    return build


@pytest.fixture
async def client_session(
    client_session_factory: Callable[
        [MCPSettings | None],
        AbstractAsyncContextManager[Client],
    ],
) -> AsyncGenerator[Client]:
    async with client_session_factory(None) as session:
        yield session


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
    assert {
        tool.name: {
            "read_only_hint": None
            if tool.annotations is None
            else tool.annotations.read_only_hint,
            "open_world_hint": None
            if tool.annotations is None
            else tool.annotations.open_world_hint,
        }
        for tool in tools_result.tools
    } == snapshot(
        {
            "list_timebase_instances": {
                "read_only_hint": True,
                "open_world_hint": False,
            },
            "get_server_configuration": {
                "read_only_hint": True,
                "open_world_hint": False,
            },
            "get_timebase_status": {
                "read_only_hint": True,
                "open_world_hint": True,
            },
            "list_timebase_activity": {
                "read_only_hint": True,
                "open_world_hint": True,
            },
            "get_timebase_activity_detail": {
                "read_only_hint": True,
                "open_world_hint": True,
            },
            "list_streams": {
                "read_only_hint": True,
                "open_world_hint": True,
            },
            "get_stream_schema": {
                "read_only_hint": True,
                "open_world_hint": True,
            },
            "get_stream_time_range": {
                "read_only_hint": True,
                "open_world_hint": True,
            },
            "list_stream_spaces": {
                "read_only_hint": True,
                "open_world_hint": True,
            },
            "get_stream_space_time_range": {
                "read_only_hint": True,
                "open_world_hint": True,
            },
            "get_stream_symbols": {
                "read_only_hint": True,
                "open_world_hint": True,
            },
            "get_stream_messages": {"read_only_hint": True, "open_world_hint": True},
            "execute_query": {"read_only_hint": False, "open_world_hint": True},
            "compile_query": {"read_only_hint": True, "open_world_hint": True},
            "list_qql_functions": {"read_only_hint": True, "open_world_hint": True},
        }
    )
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


@pytest.mark.anyio
async def test_read_resources_return_expected_text(
    monkeypatch: pytest.MonkeyPatch,
    client_session_factory: Callable[
        [MCPSettings | None],
        AbstractAsyncContextManager[Client],
    ],
) -> None:
    selected_instances: list[str | None] = []

    async def run_resource(_runtime, operation, *, instance_key=None):
        selected_instances.append(instance_key)

        class StubClient:
            def list_stream_infos(self) -> list[_StubStream]:
                return [_StubStream("bars", f"desc:{instance_key}")]

            def get_stream(self, stream_key: str) -> str:
                return stream_key

            def get_stream_schema_text(self, stream: str) -> str:
                return f"schema:{instance_key}:{stream}"

        return operation(StubClient())

    monkeypatch.setattr(resources_module, "run_with_runtime", run_resource)

    async with client_session_factory(None) as client_session:
        catalog = await client_session.read_resource("timebase://streams")
        schema = await client_session.read_resource("timebase://streams/bars/schema")
        instance_catalog = await client_session.read_resource(
            "timebase://instances/dev/streams"
        )
        instance_schema = await client_session.read_resource(
            "timebase://instances/dev/streams/bars/schema"
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
    async def fail_resource(_runtime, _operation, *, instance_key=None):
        raise TimeBaseOperationError("resource failed")

    monkeypatch.setattr(resources_module, "run_with_runtime", fail_resource)

    server = create_server(MCPSettings())
    async with Client(server, raise_exceptions=False) as client_session:
        with pytest.raises(MCPError) as error_info:
            await client_session.read_resource("timebase://streams")

    assert str(error_info.value) == "resource failed"


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

    async with Client(server, raise_exceptions=False) as client_session:
        with pytest.raises(
            MCPError,
            match=(
                r"instance_key is required when multiple TimeBase instances "
                r"are configured"
            ),
        ):
            await client_session.read_resource("timebase://streams")


@pytest.mark.anyio
async def test_read_instance_scoped_resource_uses_selected_instance_when_multiple_instances(
    monkeypatch: pytest.MonkeyPatch,
    client_session_factory: Callable[
        [MCPSettings | None],
        AbstractAsyncContextManager[Client],
    ],
) -> None:
    selected_instances: list[str | None] = []

    async def run_resource(_runtime, operation, *, instance_key=None):
        selected_instances.append(instance_key)

        class StubClient:
            def list_stream_infos(self) -> list[_StubStream]:
                return [_StubStream("bars", f"from {instance_key}")]

        return operation(StubClient())

    monkeypatch.setattr(resources_module, "run_with_runtime", run_resource)
    settings = MCPSettings.model_validate(
        {
            "servers": [
                {"name": "prod", "url": "dxtick://prod:8011"},
                {"name": "dev", "url": "dxtick://dev:8011"},
            ]
        }
    )

    async with client_session_factory(settings) as client_session:
        catalog = await client_session.read_resource("timebase://instances/dev/streams")

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
        AbstractAsyncContextManager[Client],
    ],
) -> None:
    selected_instances: list[str | None] = []

    async def run_resource(_runtime, operation, *, instance_key=None):
        selected_instances.append(instance_key)

        class StubClient:
            def list_stream_infos(self) -> list[_StubStream]:
                return [_StubStream("bars", f"from {instance_key}")]

        return operation(StubClient())

    monkeypatch.setattr(resources_module, "run_with_runtime", run_resource)
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
            "timebase://instances/dxtick%3A%2F%2Fdev%3A8011/streams"
        )

    catalog_text = [
        content.text
        for content in catalog.contents
        if isinstance(content, TextResourceContents)
    ]

    assert selected_instances == ["dxtick://dev:8011"]
    assert catalog_text == ["bars: from dxtick://dev:8011"]


@pytest.mark.anyio
async def test_read_resource_template_params_are_decoded_once(
    monkeypatch: pytest.MonkeyPatch,
    client_session_factory: Callable[
        [MCPSettings | None],
        AbstractAsyncContextManager[Client],
    ],
) -> None:
    # The SDK percent-decodes template params, so decoding them again would turn
    # 'a%2Fb' into 'a/b' and address the wrong instance or stream.
    selected_instances: list[str | None] = []

    async def run_resource(_runtime, operation, *, instance_key=None):
        selected_instances.append(instance_key)

        class StubClient:
            def list_stream_infos(self) -> list[_StubStream]:
                return [_StubStream("bars", f"from {instance_key}")]

            def get_stream(self, stream_key: str) -> str:
                return stream_key

            def get_stream_schema_text(self, stream: str) -> str:
                return f"schema:{instance_key}:{stream}"

        return operation(StubClient())

    monkeypatch.setattr(resources_module, "run_with_runtime", run_resource)

    async with client_session_factory(None) as client_session:
        await client_session.read_resource("timebase://instances/a%252Fb/streams")
        stream_schema = await client_session.read_resource(
            "timebase://streams/a%252Fb/schema"
        )
        instance_stream_schema = await client_session.read_resource(
            "timebase://instances/a%252Fb/streams/c%252Fd/schema"
        )

    assert selected_instances == ["a%2Fb", None, "a%2Fb"]
    assert _resource_text(stream_schema) == ["schema:None:a%2Fb"]
    assert _resource_text(instance_stream_schema) == ["schema:a%2Fb:c%2Fd"]


@pytest.mark.anyio
async def test_call_list_timebase_instances_tool(
    client_session_factory: Callable[
        [MCPSettings | None],
        AbstractAsyncContextManager[Client],
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

    assert result.is_error is False
    assert result.structured_content == {
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
        AbstractAsyncContextManager[Client],
    ],
) -> None:
    selected_instances: list[str | None] = []

    async def run_list_streams(
        _ctx, _operation, *, instance_key=None, report_progress=False
    ):
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

    monkeypatch.setattr(stream_tools, "run_with_context", run_list_streams)

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

        class StubClient:
            def raise_if_cancelled(self) -> None:
                return None

            def get_stream(self, stream_key: str) -> str:
                return stream_key

            def list_stream_spaces(self, stream: str):
                calls.append(("spaces", stream, None))
                return ["", "blue"]

            def get_stream_space_time_range(
                self,
                stream_key: str,
                stream: str,
                space: str,
            ):
                calls.append(("space_range", stream_key, space))
                return None, None

            def read_stream_messages(
                self,
                stream: str,
                reverse: bool,
                count: int,
                space: str | None = None,
            ) -> list[dict[str, str]]:
                assert reverse is True
                assert count == 3
                calls.append(("messages", stream, space))
                return [{"text": f"messages:{stream}:{space}"}]

        return operation(StubClient())

    monkeypatch.setattr(stream_tools, "run_with_context", run_stream_operation)

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


@pytest.mark.anyio
async def test_call_get_timebase_status_tool(
    monkeypatch: pytest.MonkeyPatch,
    client_session_factory: Callable[
        [MCPSettings | None],
        AbstractAsyncContextManager[Client],
    ],
) -> None:
    monkeypatch.delenv("DXAPI_SSL_TERMINATION", raising=False)
    monkeypatch.delenv("DXAPI_SSL_TRUST_ALL", raising=False)

    def fake_request(method: str, url: str, *, timeout: float, verify: bool, **kwargs):
        request = httpx2.Request(method, url)
        if url == "http://tb.example.com:8021/tb/ping":
            return httpx2.Response(200, request=request)
        if url == "http://tb.example.com:8021/tb/oauthinfo":
            return httpx2.Response(200, request=request, content=b"")
        if url == "http://tb.example.com:8021/tb/api/info":
            return httpx2.Response(
                200,
                request=request,
                json={
                    "version": "5.7.13",
                },
            )
        if url == "http://tb.example.com:8021/tb/api/license":
            return httpx2.Response(
                200,
                request=request,
                json={
                    "valid": True,
                    "validUntil": "2026-12-31",
                    "expirationTime": "2026-12-31",
                    "daysValid": 180,
                    "offline": False,
                    "lastValidateTime": "2026-06-29 10:00:00",
                    "clientName": "ACME",
                    "productName": "TimeBase",
                    "error": None,
                },
            )
        if url == "http://tb.example.com:8021/tb/api/server/security":
            return httpx2.Response(
                200,
                request=request,
                json={
                    "enabled": True,
                    "controllerType": "FILE",
                },
            )
        if url == "http://tb.example.com:8021/tb/api/server/system?gc=false":
            return httpx2.Response(
                200,
                request=request,
                json={
                    "timestamp": 100,
                    "cpuCount": 8,
                    "maxMemoryMb": 4096,
                    "usedMemoryMb": 1024,
                    "currentMemoryMb": 2048,
                    "availableMemoryMb": 3072,
                    "systemProperties": {"os.name": "Mac OS X", "java.version": "21"},
                },
            )
        raise AssertionError(f"unexpected URL: {url}")

    monkeypatch.setattr(
        "timebase_mcp.clients.http.transport.httpx2.request", fake_request
    )
    settings = MCPSettings(tb_http_url="http://tb.example.com:8021")

    async with client_session_factory(settings) as client_session:
        result = await client_session.call_tool("get_timebase_status", {})

    assert result.is_error is False
    assert result.structured_content is not None
    assert result.structured_content["version"] == "5.7.13"
    assert result.structured_content["security"]["enabled"] is True
    assert result.structured_content["license"]["valid_until"] == "2026-12-31"
    assert result.structured_content["runtime"]["java_version"] == "21"


@pytest.mark.anyio
async def test_call_get_server_configuration_tool(
    monkeypatch: pytest.MonkeyPatch,
    client_session_factory: Callable[
        [MCPSettings | None],
        AbstractAsyncContextManager[Client],
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
            f'  "version": "{get_version()}",\n'
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
    assert result.structured_content == {
        "version": get_version(),
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
    assert result.is_error is False


@pytest.mark.anyio
async def test_call_get_server_configuration_reports_all_timebase_instances(
    monkeypatch: pytest.MonkeyPatch,
    client_session_factory: Callable[
        [MCPSettings | None],
        AbstractAsyncContextManager[Client],
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

    assert result.is_error is False
    structured_content = result.structured_content
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


def test_build_server_configuration_reports_configured_http_url_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DXAPI_SSL_TERMINATION", raising=False)
    monkeypatch.delenv("DXAPI_SSL_TRUST_ALL", raising=False)

    configuration = build_server_configuration(
        build_runtime(MCPSettings(tb_http_url="http://localhost:8021"))
    )

    assert configuration.timebase_instances[0].http_url == "http://localhost:8021"


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

    assert result.structured_content == {
        "version": get_version(),
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

    assert result.structured_content == {
        "version": get_version(),
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

    assert result.structured_content == {
        "version": get_version(),
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
        "run_with_context",
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
        "run_with_context",
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

    monkeypatch.setattr(query_tools, "run_with_context", fail_operation)

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
        "run_with_context",
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
