from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager

import httpx2
import pytest
from mcp.client import Client
from mcp_types import TextContent
from pydantic import SecretStr

from timebase_mcp.auth.oauth2 import OAuth2PasswordConfig
from timebase_mcp.config.settings import MCPSettings
from timebase_mcp.config.webadmin import WebAdminAuthConfig, WebAdminConfig
from timebase_mcp.server import create_server

ClientSessionFactory = Callable[
    [MCPSettings | None],
    AbstractAsyncContextManager[Client],
]


@pytest.mark.parametrize("mode", ["auto", "legacy"])
@pytest.mark.anyio
async def test_webadmin_tool_is_registered_only_when_configured(
    mode: str,
) -> None:
    async with Client(create_server(MCPSettings()), mode=mode) as client_session:
        default_tools = await client_session.list_tools()

    settings = MCPSettings(webadmin=WebAdminConfig(url="http://webadmin.example.com/"))
    async with Client(create_server(settings), mode=mode) as client_session:
        configured_tools = await client_session.list_tools()

    assert "get_webadmin_info" not in {tool.name for tool in default_tools.tools}
    assert {tool.name for tool in configured_tools.tools}.issuperset(
        {
            "get_webadmin_info",
            "list_webadmin_views",
            "get_webadmin_view",
            "list_webadmin_topics",
            "get_webadmin_topic_schema",
            "get_webadmin_background_task_status",
            "list_order_book_validation_issues",
        }
    )


@pytest.mark.parametrize("mode", ["auto", "legacy"])
@pytest.mark.anyio
async def test_authenticated_webadmin_tools(
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    provider_configs: list[OAuth2PasswordConfig] = []

    class FakeProvider:
        def __init__(self, config: OAuth2PasswordConfig) -> None:
            provider_configs.append(config)

        def get_access_token(self) -> str:
            return "webadmin-token"

    def fake_request(
        method: str,
        url: str,
        *,
        timeout: float = 3.0,
        verify: bool = True,
        **kwargs: object,
    ) -> httpx2.Response:
        del timeout, verify
        request = httpx2.Request(method, url)
        if url == "http://webadmin.example.com/api/v0/authInfo":
            assert kwargs.get("headers") is None
            return httpx2.Response(
                200,
                request=request,
                json={
                    "provider_type": "BUILT_IN_OAUTH",
                    "oauth_server": "http://webadmin.example.com",
                    "token_endpoint": "/oauth/token",
                    "scopes": ["openid", "profile"],
                },
            )

        assert kwargs.get("headers") == {"Authorization": "Bearer webadmin-token"}
        payloads: dict[str, object] = {
            "http://webadmin.example.com/api/v0/timebase/views": [
                {"id": "z-view", "state": "IDLE", "paused": True},
                {"id": "a-view", "state": "PROCESSING"},
            ],
            "http://webadmin.example.com/api/v0/timebase/views/a%2Fb": {
                "id": "a/b",
                "lastTimestamp": 123,
                "query": "select * from bars",
            },
            "http://webadmin.example.com/api/v0/topics": ["z-topic", "a-topic"],
            "http://webadmin.example.com/api/v0/topics/a%2Fb/schema": {
                "types": [{"name": "Trade"}],
                "all": [{"name": "Trade"}],
            },
            "http://webadmin.example.com/api/v0/bars%2Fraw/options/backgroundTask": {
                "referToStream": "bars/raw",
                "isFinished": False,
                "progress": 0.5,
                "status": "Running",
            },
            "http://webadmin.example.com/api/v0/orderBookValidation/report/"
            "report%2F1/issues?offset=5&rows=10&severity=ERROR&symbol=A%2FB": {
                "issues": [
                    {
                        "timestampNs": "123456789",
                        "symbol": "A/B",
                        "severity": "ERROR",
                        "message": "bad book",
                        "source": "L2",
                    }
                ],
                "offset": 5,
                "rows": 10,
                "hasMore": False,
                "inlineOnly": False,
                "warningMessage": None,
            },
        }
        if url not in payloads:
            raise AssertionError(f"unexpected URL: {url}")
        return httpx2.Response(200, request=request, json=payloads[url])

    monkeypatch.setattr(
        "timebase_mcp.clients.webadmin.OAuth2PasswordProvider",
        FakeProvider,
    )
    monkeypatch.setattr(
        "timebase_mcp.clients.webadmin.http_request",
        fake_request,
    )
    settings = MCPSettings(
        webadmin=WebAdminConfig(
            url="http://webadmin.example.com",
            auth=WebAdminAuthConfig(
                username="webadmin-user",
                password=SecretStr("webadmin-password"),
                client_id="inspector",
                client_secret=SecretStr("inspector-secret"),
            ),
        ),
    )

    async with Client(create_server(settings), mode=mode) as client_session:
        catalog = await client_session.list_tools()
        output_schemas = {tool.name: tool.output_schema for tool in catalog.tools}
        views = await client_session.call_tool("list_webadmin_views", {})
        view = await client_session.call_tool(
            "get_webadmin_view",
            {"view_id": "a/b"},
        )
        topics = await client_session.call_tool("list_webadmin_topics", {})
        schema = await client_session.call_tool(
            "get_webadmin_topic_schema",
            {"topic_id": "a/b"},
        )
        task = await client_session.call_tool(
            "get_webadmin_background_task_status",
            {"stream_id": "bars/raw"},
        )
        issues = await client_session.call_tool(
            "list_order_book_validation_issues",
            {
                "report_id": "report/1",
                "offset": 5,
                "rows": 10,
                "severity": "ERROR",
                "symbol": "A/B",
            },
        )

    assert views.structured_content is not None
    assert [item["id"] for item in views.structured_content["items"]] == [
        "a-view",
        "z-view",
    ]
    assert view.structured_content["last_timestamp"] == 123
    assert topics.structured_content["items"] == ["a-topic", "z-topic"]
    assert schema.structured_content["types"] == [{"name": "Trade"}]
    assert task.structured_content["refer_to_stream"] == "bars/raw"
    assert issues.structured_content["issues"][0]["timestamp_ns"] == "123456789"
    view_schema = output_schemas["get_webadmin_view"]
    views_schema = output_schemas["list_webadmin_views"]
    issues_schema = output_schemas["list_order_book_validation_issues"]
    assert view_schema is not None
    assert views_schema is not None
    assert issues_schema is not None
    assert set(view_schema["properties"]) == set(view.structured_content)
    assert set(views_schema["$defs"]["WebAdminView"]["properties"]) == set(
        views.structured_content["items"][0]
    )
    assert set(issues_schema["$defs"]["OrderBookValidationIssue"]["properties"]) == set(
        issues.structured_content["issues"][0]
    )
    assert provider_configs == [
        OAuth2PasswordConfig(
            token_url="http://webadmin.example.com/oauth/token",
            username="webadmin-user",
            password="webadmin-password",
            client_id="inspector",
            client_secret="inspector-secret",
            scope="trust",
        )
    ]


@pytest.mark.parametrize("mode", ["auto", "legacy"])
@pytest.mark.anyio
async def test_get_webadmin_info(
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    def fake_request(
        method: str,
        url: str,
        *,
        timeout: float = 3.0,
        verify: bool = True,
        **kwargs: object,
    ) -> httpx2.Response:
        request = httpx2.Request(method, url)
        if url == "http://webadmin.example.com/api/v0/v":
            return httpx2.Response(
                200,
                request=request,
                json={
                    "name": "TimeBase Web Admin",
                    "version": "1.2.3",
                    "timestamp": 1_717_171_717,
                    "authentication": True,
                    "timebase": {
                        "connected": True,
                        "clientVersion": "6.2.0",
                        "serverVersion": "6.1.0",
                    },
                },
            )
        if url == "http://webadmin.example.com/api/v0/authInfo":
            return httpx2.Response(
                200,
                request=request,
                json={
                    "provider_type": "OAUTH2",
                    "oauth_server": "https://idp.example.com",
                    "token_endpoint": "https://idp.example.com/token",
                    "scopes": ["openid"],
                },
            )
        raise AssertionError(f"unexpected URL: {url}")

    monkeypatch.setattr(
        "timebase_mcp.clients.webadmin.http_request",
        fake_request,
    )
    settings = MCPSettings(webadmin=WebAdminConfig(url="http://webadmin.example.com"))

    async with Client(create_server(settings), mode=mode) as client_session:
        catalog = await client_session.list_tools()
        output_schema = next(
            tool.output_schema
            for tool in catalog.tools
            if tool.name == "get_webadmin_info"
        )
        result = await client_session.call_tool("get_webadmin_info", {})

    assert result.is_error is False
    assert result.structured_content == {
        "instance_key": "default",
        "url": "http://webadmin.example.com",
        "name": "TimeBase Web Admin",
        "version": "1.2.3",
        "timestamp": 1_717_171_717,
        "authentication_enabled": True,
        "timebase": {
            "connected": True,
            "client_version": "6.2.0",
            "server_version": "6.1.0",
        },
        "authentication": {
            "provider_type": "OAUTH2",
            "oauth_server": "https://idp.example.com",
            "token_endpoint": "https://idp.example.com/token",
            "scopes": ["openid"],
        },
    }
    assert output_schema is not None
    assert set(output_schema["$defs"]["WebAdminTimeBaseInfo"]["properties"]) == set(
        result.structured_content["timebase"]
    )


@pytest.mark.anyio
async def test_get_webadmin_info_reports_connection_failure_at_call_time(
    monkeypatch: pytest.MonkeyPatch,
    client_session_factory: ClientSessionFactory,
) -> None:
    def fail_request(*args: object, **kwargs: object) -> httpx2.Response:
        raise httpx2.ConnectError("connection refused")

    monkeypatch.setattr(
        "timebase_mcp.clients.webadmin.http_request",
        fail_request,
    )
    settings = MCPSettings(webadmin=WebAdminConfig(url="http://webadmin.example.com"))

    async with client_session_factory(settings) as client_session:
        result = await client_session.call_tool("get_webadmin_info", {})
        tools = await client_session.list_tools()

    assert result.is_error is True
    assert "get_webadmin_info" in {tool.name for tool in tools.tools}
    error = result.content[0]
    assert isinstance(error, TextContent)
    assert error.text == (
        "Error executing tool get_webadmin_info: "
        "WebAdmin endpoint http://webadmin.example.com is unavailable (ConnectError)."
    )


@pytest.mark.anyio
async def test_get_webadmin_info_requires_url_for_selected_instance(
    client_session_factory: ClientSessionFactory,
) -> None:
    settings = MCPSettings.model_validate(
        {
            "servers": [
                {"name": "plain", "url": "dxtick://plain:8011"},
                {
                    "name": "web",
                    "url": "dxtick://web:8011",
                    "webadmin_url": "http://webadmin.example.com",
                },
            ]
        }
    )

    async with client_session_factory(settings) as client_session:
        result = await client_session.call_tool(
            "get_webadmin_info",
            {"instance_key": "plain"},
        )

    assert result.is_error is True
    error = result.content[0]
    assert isinstance(error, TextContent)
    assert error.text == (
        "Error executing tool get_webadmin_info: "
        "TimeBase instance 'plain' has no WebAdmin URL configured."
    )


@pytest.mark.anyio
async def test_protected_webadmin_tool_requires_username_and_password(
    client_session_factory: ClientSessionFactory,
) -> None:
    settings = MCPSettings(
        webadmin=WebAdminConfig(url="http://webadmin.example.com"),
        tb_username="timebase-user",
        tb_password=SecretStr("timebase-password"),
    )

    async with client_session_factory(settings) as client_session:
        result = await client_session.call_tool("list_webadmin_topics", {})

    assert result.is_error is True
    error = result.content[0]
    assert isinstance(error, TextContent)
    assert "requires TIMEBASE_WEBADMIN_USERNAME" in error.text
