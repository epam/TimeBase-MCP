from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager

import httpx2
import pytest
from mcp.client import Client
from mcp_types import TextContent
from pydantic import SecretStr

from timebase_mcp.clients import factory as client_factory
from timebase_mcp.config.settings import MCPSettings
from timebase_mcp.runtime.introspection import build_server_configuration
from timebase_mcp.runtime.state import build_runtime
from timebase_mcp.tools import system as system_tools
from timebase_mcp.version import get_version


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
                "read_only": False,
            },
            {
                "name": "dxtick://dev:8011",
                "description": None,
                "read_only": False,
            },
        ]
    }


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
            '      "read_only": false,\n'
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
                "read_only": False,
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
            "read_only": False,
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
            "read_only": False,
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
                "read_only": False,
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
                "read_only": False,
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
                "read_only": False,
                "dxapi_ssl_termination": False,
                "dxapi_ssl_trust_all": False,
            }
        ],
    }


@pytest.mark.anyio
async def test_call_list_timebase_instances_reports_read_only(
    client_session_factory: Callable[
        [MCPSettings | None],
        AbstractAsyncContextManager[Client],
    ],
) -> None:
    settings = MCPSettings.model_validate(
        {
            "tb_read_only": True,
            "servers": [
                {"name": "prod", "url": "dxtick://prod:8011"},
                {"name": "dev", "url": "dxtick://dev:8011", "read_only": False},
            ],
        }
    )

    async with client_session_factory(settings) as client_session:
        result = await client_session.call_tool("list_timebase_instances", {})

    assert result.is_error is False
    assert result.structured_content == {
        "result": [
            {"name": "prod", "description": None, "read_only": True},
            {"name": "dev", "description": None, "read_only": False},
        ]
    }


def test_build_server_configuration_reports_read_only_instances() -> None:
    settings = MCPSettings.model_validate(
        {
            "servers": [
                {"name": "prod", "url": "dxtick://prod:8011", "read_only": True},
                {"name": "dev", "url": "dxtick://dev:8011"},
            ]
        }
    )

    configuration = build_server_configuration(build_runtime(settings))

    assert [instance.read_only for instance in configuration.timebase_instances] == [
        True,
        False,
    ]


@pytest.mark.anyio
async def test_call_get_timebase_activity_detail_rejects_empty_id(
    monkeypatch: pytest.MonkeyPatch,
    client_session_factory: Callable[
        [MCPSettings | None],
        AbstractAsyncContextManager[Client],
    ],
) -> None:
    executed = False

    async def get_activity_detail(*args, **kwargs):
        nonlocal executed
        executed = True
        raise AssertionError("should not run")

    monkeypatch.setattr(system_tools, "get_activity_detail", get_activity_detail)

    async with client_session_factory(None) as client_session:
        result = await client_session.call_tool(
            "get_timebase_activity_detail",
            {"kind": "cursor", "id": ""},
        )

    assert result.is_error is True
    assert executed is False
