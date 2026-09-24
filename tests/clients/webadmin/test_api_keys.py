from __future__ import annotations

import base64
import hashlib
import hmac

import httpx2
import pytest
from pydantic import SecretStr, ValidationError

from timebase_mcp.clients import webadmin
from timebase_mcp.config.servers import ServerConfig
from timebase_mcp.config.settings import MCPSettings
from timebase_mcp.config.webadmin import WebAdminAuthConfig, WebAdminConfig
from timebase_mcp.errors import TimeBaseOperationError
from timebase_mcp.runtime.state import build_runtime


def test_key_signs_exact_request_without_oauth(monkeypatch: pytest.MonkeyPatch) -> None:
    instance = build_runtime(
        MCPSettings(
            webadmin=WebAdminConfig(
                url="https://example.test/gateway",
                auth=WebAdminAuthConfig(
                    api_key="reader", api_secret=SecretStr("fixture-secret")
                ),
            ),
        )
    ).get_instance()
    calls = []

    def request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return httpx2.Response(200, json=[], request=httpx2.Request(method, url))

    monkeypatch.setattr(webadmin, "http_request", request)
    endpoint = "/api/v0/%74opics?z=2&A=z&a=b&a=a&empty=&q=a+b"
    assert webadmin.get_webadmin_payload(instance, endpoint) == []
    assert len(calls) == 1
    method, url, kwargs = calls[0]
    assert method == "GET"
    assert url == "https://example.test/gateway" + endpoint
    expected = base64.b64encode(
        hmac.new(
            b"fixture-secret",
            b"GET/api/v0/topicsa=z&a=a&a=b&empty=&q=a b&z=2",
            hashlib.sha384,
        ).digest()
    ).decode()
    assert kwargs["headers"] == {
        "X-Deltix-ApiKey": "reader",
        "X-Deltix-Signature": expected,
    }
    assert kwargs["follow_redirects"] is False
    assert kwargs["max_response_bytes"] == 128 * 1024
    assert instance.webadmin_provider is None


@pytest.mark.parametrize("status", [400, 401, 403, 302])
def test_key_errors_are_bounded_without_fallback(
    monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    instance = build_runtime(
        MCPSettings(
            webadmin=WebAdminConfig(
                url="https://example.test",
                auth=WebAdminAuthConfig(
                    api_key="reader", api_secret=SecretStr("private-fixture")
                ),
            ),
        )
    ).get_instance()
    calls = []

    def request(method, url, **kwargs):
        calls.append(url)
        return httpx2.Response(
            status, text="private-fixture", request=httpx2.Request(method, url)
        )

    monkeypatch.setattr(webadmin, "http_request", request)
    with pytest.raises(TimeBaseOperationError) as error:
        webadmin.get_webadmin_payload(instance, "/api/v0/topics")
    assert "private-fixture" not in str(error.value)
    assert len(calls) == 1


@pytest.mark.parametrize(
    "fields",
    [
        {"webadmin_api_key": "reader"},
        {"webadmin_api_secret": "secret"},
        {"webadmin_api_key": "", "webadmin_api_secret": "secret"},
        {"webadmin_api_key": "reader", "webadmin_api_secret": ""},
        {
            "webadmin_api_key": "reader",
            "webadmin_api_secret": "secret",
            "webadmin_username": "admin",
            "webadmin_password": "password",
        },
        {
            "webadmin_api_key": "reader",
            "webadmin_api_secret": "secret",
            "webadmin_client_id": "web",
            "webadmin_client_secret": "secret",
        },
    ],
)
def test_invalid_key_config_fails_in_flat_and_server_settings(
    fields: dict[str, str],
) -> None:
    with pytest.raises(ValidationError):
        ServerConfig.model_validate({"url": "dxtick://localhost:8011", **fields})
    with pytest.raises(ValidationError):
        MCPSettings.model_validate({"tb_" + k: v for k, v in fields.items()})


def test_key_environment_loading_and_redaction(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TIMEBASE_WEBADMIN_API_KEY", "reader")
    monkeypatch.setenv("TIMEBASE_WEBADMIN_API_SECRET", "private-fixture")
    settings = MCPSettings()
    server = settings.resolve_servers()[0]
    assert server.webadmin.auth.api_key == "reader"
    assert server.webadmin.auth.api_secret == SecretStr("private-fixture")
    assert "private-fixture" not in str(settings.debug_log_payload())
    assert "private-fixture" not in str(MCPSettings.debug_log_payload_from_env())
    monkeypatch.delenv("TIMEBASE_WEBADMIN_API_KEY")
    monkeypatch.delenv("TIMEBASE_WEBADMIN_API_SECRET")
    monkeypatch.setenv("TIMEBASE_SERVERS_0_URL", "dxtick://localhost:8011")
    monkeypatch.setenv("TIMEBASE_SERVERS_0_WEBADMIN_API_KEY", "writer")
    monkeypatch.setenv("TIMEBASE_SERVERS_0_WEBADMIN_API_SECRET", "indexed-fixture")
    indexed = MCPSettings().resolve_servers()[0]
    assert indexed.webadmin.auth.api_key == "writer"
    assert indexed.webadmin.auth.api_secret == SecretStr("indexed-fixture")
