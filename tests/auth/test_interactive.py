from __future__ import annotations

from urllib import parse

import pytest

from tests.auth.helpers import (
    interactive_provider,
)
from tests.auth.test_oauth2 import token_response as endpoint_response
from timebase_mcp.auth.discovery import (
    InteractiveEndpoints,
)
from timebase_mcp.auth.interactive import (
    InteractiveOAuthProvider,
    resolve_interactive_redirect_uri,
)
from timebase_mcp.auth.oauth2 import TokenResponse, UrlLibTokenEndpointClient
from timebase_mcp.auth.webadmin_oauth import WebAdminInteractiveProvider
from timebase_mcp.config.env import SettingsEnv
from timebase_mcp.config.settings import MCPSettings
from timebase_mcp.errors import ConfigurationError


@pytest.mark.parametrize(
    ("host", "port", "expected"),
    [
        ("127.0.0.1", 8000, "http://127.0.0.1:8000/"),
        ("localhost", 4276, "http://localhost:4276/"),
        ("0.0.0.0", 8765, "http://127.0.0.1:8765/"),
    ],
)
def test_resolve_interactive_redirect_uri(host: str, port: int, expected: str) -> None:
    assert resolve_interactive_redirect_uri(host=host, port=port) == expected


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


def testinteractive_provider_posts_token_form_with_content_type() -> None:
    provider = interactive_provider()
    captured: dict[str, object] = {}

    def urlopen(req, *, timeout):
        captured["url"] = req.full_url
        captured["data"] = parse.parse_qs(req.data.decode())
        captured["headers"] = {key.lower(): value for key, value in req.header_items()}
        captured["timeout"] = timeout
        return endpoint_response({"access_token": "access-1", "expires_in": 120})

    provider._token_endpoint = UrlLibTokenEndpointClient(urlopen=urlopen)

    token_response = provider._post_token(
        "https://idp.example/token",
        {"grant_type": "authorization_code", "code": "code-1"},
    )

    assert token_response.access_token == "access-1"
    assert captured == {
        "url": "https://idp.example/token",
        "data": {"grant_type": ["authorization_code"], "code": ["code-1"]},
        "headers": {
            "accept": "application/json",
            "content-type": "application/x-www-form-urlencoded",
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

    provider._store_token(TokenResponse(access_token="a", expires_at_monotonic=1010.0))
    assert provider._token_expired() is True

    provider._store_token(TokenResponse(access_token="a", expires_at_monotonic=4600.0))
    assert provider._token_expired() is False

    clock["now"] = 1000.0 + 3600
    assert provider._token_expired() is True

    provider._store_token(TokenResponse(access_token="a"))
    assert provider._token_expired() is False


@pytest.mark.parametrize("grant", ["authorization_code", "refresh_token"])
@pytest.mark.parametrize("returned_refresh", [None, "rotated-refresh"])
def test_refresh_token_belongs_to_current_login(monkeypatch, grant, returned_refresh):
    provider = InteractiveOAuthProvider()
    endpoints = InteractiveEndpoints(
        "https://idp.example/auth", "https://idp.example/token", "client", "scope"
    )
    provider._endpoints = endpoints
    provider._refresh_token = "previous-refresh"
    calls = []

    def post(url, data):
        calls.append(data)
        return TokenResponse(
            access_token="current-access", refresh_token=returned_refresh
        )

    monkeypatch.setattr(provider, "_post_token", post)
    if grant == "authorization_code":
        provider._exchange_code(endpoints, "code", "verifier", "http://localhost:8765/")
        expected_refresh = returned_refresh
    else:
        provider._refresh()
        expected_refresh = returned_refresh or "previous-refresh"
    assert calls[0]["grant_type"] == grant
    assert provider.get_access_token() == "current-access"
    assert len(calls) == 1
    assert provider._refresh_token == expected_refresh


@pytest.mark.parametrize(
    "provider_type", [InteractiveOAuthProvider, WebAdminInteractiveProvider]
)
@pytest.mark.parametrize("status", [206, 302, 401])
def test_interactive_token_transport_rejects_status_and_redacts(provider_type, status):
    import io
    from email.message import Message
    from urllib.error import HTTPError

    body = b'{"access_token":"private-access","error_description":"private-detail"}'
    response = endpoint_response(body, status=status)
    failure = HTTPError(
        "https://idp.example/token", status, "rejected", Message(), io.BytesIO(body)
    )

    def urlopen(*args, **kwargs):
        if status >= 300:
            raise failure
        return response

    provider = provider_type()
    provider._token_endpoint = UrlLibTokenEndpointClient(urlopen=urlopen)
    with pytest.raises(
        PermissionError if status == 401 else ConnectionError, match=f"HTTP {status}"
    ) as exc:
        provider._post_token(
            "https://idp.example/token", {"grant_type": "authorization_code"}
        )
    assert "private-" not in str(exc.value)
    assert (failure if status >= 300 else response).closed
