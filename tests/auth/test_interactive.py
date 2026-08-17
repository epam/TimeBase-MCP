from __future__ import annotations

import json

import pytest

from timebase_mcp.auth.discovery import (
    InteractiveEndpoints,
)
from timebase_mcp.auth.interactive import (
    InteractiveOAuthProvider,
    resolve_interactive_redirect_uri,
)
from timebase_mcp.config.env import SettingsEnv
from timebase_mcp.config.settings import MCPSettings
from timebase_mcp.errors import ConfigurationError

from tests.auth.helpers import (
    interactive_provider,
)


def test_resolve_interactive_redirect_uri_defaults_to_mcp_host_port() -> None:
    assert (
        resolve_interactive_redirect_uri(
            host="127.0.0.1",
            port=8000,
        )
        == "http://127.0.0.1:8000/"
    )


def test_resolve_interactive_redirect_uri_preserves_localhost() -> None:
    assert (
        resolve_interactive_redirect_uri(
            host="localhost",
            port=4276,
        )
        == "http://localhost:4276/"
    )


def test_resolve_interactive_redirect_uri_normalizes_wildcard_host() -> None:
    assert (
        resolve_interactive_redirect_uri(
            host="0.0.0.0",
            port=8765,
        )
        == "http://127.0.0.1:8765/"
    )


def test_settings_resolved_interactive_redirect_uri(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(SettingsEnv.MCP_HOST, "0.0.0.0")
    monkeypatch.setenv(SettingsEnv.MCP_PORT, "8123")

    settings = MCPSettings()

    assert settings.resolved_interactive_redirect_uri == "http://127.0.0.1:8123/"


def test_settings_resolved_interactive_redirect_uri_preserves_localhost(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(SettingsEnv.MCP_HOST, "localhost")
    monkeypatch.setenv(SettingsEnv.MCP_PORT, "4276")

    settings = MCPSettings()

    assert settings.resolved_interactive_redirect_uri == "http://localhost:4276/"


def test_settings_resolved_interactive_redirect_uri_is_none_for_http(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(SettingsEnv.MCP_TRANSPORT, "streamable-http")

    settings = MCPSettings()

    assert settings.resolved_interactive_redirect_uri is None


def testinteractive_provider_refreshes_and_caches() -> None:
    provider = interactive_provider()
    provider._refresh_token = "refresh-1"

    calls: list[dict] = []

    def stub_post(_url: str, data: dict):
        calls.append(data)
        from timebase_mcp.auth.oauth2 import parse_token_response

        return parse_token_response(
            {
                "access_token": "access-1",
                "refresh_token": "refresh-2",
                "expires_in": 3600,
            },
            monotonic=provider._monotonic,
            access_token_error="OAuth token response did not include an access_token.",
        )

    provider._post_token = stub_post  # type: ignore[assignment]

    assert provider.get_access_token() == "access-1"
    assert calls[0]["grant_type"] == "refresh_token"

    assert provider.get_access_token() == "access-1"
    assert len(calls) == 1


def testinteractive_provider_posts_token_form_with_content_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = interactive_provider()
    captured: dict[str, object] = {}

    class _Response:
        text = json.dumps({"access_token": "access-1", "expires_in": 120})

        def raise_for_status(self) -> None:
            return

    def fake_post(url: str, *, data: dict, headers: dict, timeout: float):
        captured["url"] = url
        captured["data"] = data
        captured["headers"] = headers
        captured["timeout"] = timeout
        return _Response()

    monkeypatch.setattr("timebase_mcp.auth.interactive.httpx2.post", fake_post)

    token_response = provider._post_token(
        "https://idp.example/token",
        {"grant_type": "authorization_code", "code": "code-1"},
    )

    assert token_response.access_token == "access-1"
    assert captured == {
        "url": "https://idp.example/token",
        "data": {"grant_type": "authorization_code", "code": "code-1"},
        "headers": {
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        "timeout": 30,
    }


def testinteractive_provider_requires_redirect_uri_on_login() -> None:
    provider = InteractiveOAuthProvider()
    provider._endpoints = InteractiveEndpoints(
        authorization_endpoint="https://idp.example/auth",
        token_endpoint="https://idp.example/token",
        client_id="tb-app",
        scope="openid",
    )

    with pytest.raises(ConfigurationError, match="redirect URI is not configured"):
        provider._login()


def testinteractive_provider_token_expiry() -> None:
    clock = {"now": 1000.0}
    provider = InteractiveOAuthProvider(
        redirect_uri="http://127.0.0.1:8000/",
        monotonic=lambda: clock["now"],
    )

    provider._store_token({"access_token": "a", "expires_in": 10})
    assert provider._token_expired() is True

    provider._store_token({"access_token": "a", "expires_in": 3600})
    assert provider._token_expired() is False

    clock["now"] = 1000.0 + 3600
    assert provider._token_expired() is True

    provider._store_token({"access_token": "a"})
    assert provider._token_expired() is False
