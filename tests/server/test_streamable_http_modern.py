"""Smoke tests for the 2026-07-28 stateless Streamable HTTP path."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import LATEST_PROTOCOL_VERSION
from starlette.testclient import TestClient

from tests.support.mcp_http import (
    PROTOCOL_VERSION,
    build_client_meta,
    build_modern_headers,
    parse_jsonrpc_response,
)
from timebase_mcp.config.settings import MCPSettings
from timebase_mcp.constants import APP_NAME, APP_WEBSITE_URL
from timebase_mcp.server import create_server
from timebase_mcp.version import get_version

_CLIENT_META = build_client_meta(client_name="timebase-mcp-modern-smoke")


@pytest.fixture
def modern_http_client() -> Iterator[TestClient]:
    server = create_server(MCPSettings())
    app = server.streamable_http_app(
        # Keep the default SSE-capable transport; modern requests are still
        # sessionless without opting into legacy-only stateless_http.
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=False,
        ),
    )
    with TestClient(app) as client:
        yield client


def _post_mcp(
    client: TestClient,
    *,
    method: str,
    request_id: int,
    params: dict[str, Any] | None = None,
    mcp_name: str | None = None,
) -> dict[str, Any]:
    response, payload = _post_mcp_raw(
        client,
        method=method,
        request_id=request_id,
        params=params,
        mcp_name=mcp_name,
        include_meta=True,
    )
    assert response.status_code == 200
    assert response.headers.get("mcp-session-id") is None
    assert payload.get("id") == request_id
    assert "error" not in payload
    result = payload.get("result")
    assert isinstance(result, dict)
    return result


def _post_mcp_raw(
    client: TestClient,
    *,
    method: str,
    request_id: int,
    params: dict[str, Any] | None = None,
    mcp_name: str | None = None,
    include_meta: bool = True,
    protocol_version: str | None = PROTOCOL_VERSION,
    include_method_header: bool = True,
) -> tuple[Any, dict[str, Any]]:
    body_params = dict(params or {})
    if include_meta:
        body_params["_meta"] = _CLIENT_META

    response = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": body_params,
        },
        headers=build_modern_headers(
            method=method,
            mcp_name=mcp_name,
            protocol_version=protocol_version,
            include_method_header=include_method_header,
        ),
    )
    payload = parse_jsonrpc_response(response)
    assert payload is not None
    return response, payload


def _assert_server_info(meta: dict[str, Any]) -> None:
    server_info = meta["io.modelcontextprotocol/serverInfo"]
    assert server_info["name"] == APP_NAME
    assert server_info["version"] == get_version()
    assert server_info["websiteUrl"] == APP_WEBSITE_URL


def test_pinned_protocol_version_matches_locked_sdk() -> None:
    assert PROTOCOL_VERSION == LATEST_PROTOCOL_VERSION


def test_server_discover_is_sessionless_and_identifies_server(
    modern_http_client: TestClient,
) -> None:
    result = _post_mcp(
        modern_http_client,
        method="server/discover",
        request_id=1,
    )

    assert result["resultType"] == "complete"
    assert PROTOCOL_VERSION in result["supportedVersions"]
    assert "ttlMs" in result
    assert result["cacheScope"] in {"public", "private"}
    assert "tools" in result["capabilities"]
    _assert_server_info(result["_meta"])
    assert "list_timebase_instances" in result["instructions"]


def test_tools_list_and_call_are_sessionless(
    modern_http_client: TestClient,
) -> None:
    listed = _post_mcp(
        modern_http_client,
        method="tools/list",
        request_id=2,
    )
    assert listed["resultType"] == "complete"
    assert "ttlMs" in listed
    assert listed["cacheScope"] in {"public", "private"}
    tool_names = [tool["name"] for tool in listed["tools"]]
    assert tool_names[0] == "list_timebase_instances"
    assert "get_server_configuration" in tool_names
    assert "execute_query" in tool_names

    # A second request with a new id must not depend on prior session state.
    called = _post_mcp(
        modern_http_client,
        method="tools/call",
        request_id=3,
        params={
            "name": "list_timebase_instances",
            "arguments": {},
        },
        mcp_name="list_timebase_instances",
    )
    assert called["resultType"] == "complete"
    assert called.get("isError") is False
    structured = called["structuredContent"]["result"]
    assert structured[0]["name"] == "default"
    _assert_server_info(called["_meta"])


def test_resources_list_and_templates_are_sessionless(
    modern_http_client: TestClient,
) -> None:
    resources = _post_mcp(
        modern_http_client,
        method="resources/list",
        request_id=4,
    )
    assert resources["resultType"] == "complete"
    assert [resource["name"] for resource in resources["resources"]] == [
        "stream_catalog"
    ]
    assert resources["resources"][0]["uri"] == "timebase://streams"
    _assert_server_info(resources["_meta"])

    templates = _post_mcp(
        modern_http_client,
        method="resources/templates/list",
        request_id=5,
    )
    assert templates["resultType"] == "complete"
    template_names = [item["name"] for item in templates["resourceTemplates"]]
    assert template_names == [
        "stream_schema",
        "instance_stream_catalog",
        "instance_stream_schema",
    ]
    assert [item["uriTemplate"] for item in templates["resourceTemplates"]] == [
        "timebase://streams/{stream_key}/schema",
        "timebase://instances/{instance_key}/streams",
        "timebase://instances/{instance_key}/streams/{stream_key}/schema",
    ]


def test_modern_request_without_meta_is_rejected(
    modern_http_client: TestClient,
) -> None:
    response, payload = _post_mcp_raw(
        modern_http_client,
        method="tools/list",
        request_id=6,
        include_meta=False,
    )

    assert response.status_code == 400
    assert response.headers.get("mcp-session-id") is None
    assert payload["id"] == 6
    error = payload["error"]
    assert error["code"] == -32602
    assert "params._meta" in error["message"]
    assert "protocolVersion" in error["message"]


def test_request_without_protocol_version_header_is_not_modern(
    modern_http_client: TestClient,
) -> None:
    # Without MCP-Protocol-Version the SDK treats the call as legacy and
    # requires a session; modern clients must send the header.
    response, payload = _post_mcp_raw(
        modern_http_client,
        method="tools/list",
        request_id=7,
        protocol_version=None,
    )

    assert response.status_code == 400
    error = payload["error"]
    assert error["code"] == -32600
    assert "Missing session ID" in error["message"]
