from __future__ import annotations

import pytest
from pydantic import ValidationError

from timebase_mcp.config.env import SettingsEnv
from timebase_mcp.config.settings import MCPSettings


def test_url_only_http_transport_still_defaults_to_auto(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(SettingsEnv.MCP_TRANSPORT, "streamable-http")

    settings = MCPSettings()

    assert settings.resolve_servers()[0].auth_mode == "auto"


def test_forward_identity_requires_inbound_auth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(SettingsEnv.TIMEBASE_AUTH_MODE, "forward_identity")

    with pytest.raises(ValidationError, match="forward_identity"):
        MCPSettings()


def test_forward_identity_on_stdio_fails_even_with_audience(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(SettingsEnv.TIMEBASE_AUTH_MODE, "forward_identity")
    monkeypatch.setenv(SettingsEnv.MCP_AUTH_AUDIENCE, "timebase-api")

    with pytest.raises(ValidationError, match="inbound auth"):
        MCPSettings()


def test_forward_identity_valid_on_http_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(SettingsEnv.TIMEBASE_AUTH_MODE, "forward_identity")
    monkeypatch.setenv(SettingsEnv.MCP_TRANSPORT, "streamable-http")
    monkeypatch.setenv(SettingsEnv.MCP_AUTH_PUBLIC_URL, "https://mcp.example.com/mcp")
    monkeypatch.setenv(SettingsEnv.MCP_AUTH_AUDIENCE, "timebase-api")

    settings = MCPSettings()

    assert settings.resolve_servers()[0].auth_mode == "forward_identity"


def test_interactive_mode_allows_url_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(SettingsEnv.TIMEBASE_AUTH_MODE, "interactive")

    settings = MCPSettings()

    assert settings.resolve_servers()[0].auth_mode == "interactive"


def test_interactive_mode_allows_client_id_and_scope_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(SettingsEnv.TIMEBASE_AUTH_MODE, "interactive")
    monkeypatch.setenv(SettingsEnv.TIMEBASE_OAUTH2_CLIENT_ID, "interactive-client")
    monkeypatch.setenv(SettingsEnv.TIMEBASE_OAUTH2_SCOPE, "openid profile")

    settings = MCPSettings()
    server = settings.resolve_servers()[0]

    assert server.auth_mode == "interactive"
    assert server.oauth2_client_id == "interactive-client"
    assert server.oauth2_scope == "openid profile"


@pytest.mark.parametrize(
    ("env_var", "value"),
    [
        (SettingsEnv.TIMEBASE_OAUTH2_TOKEN_URL, "https://idp.example/token"),
        (SettingsEnv.TIMEBASE_OAUTH2_CLIENT_SECRET, "secret"),
        (SettingsEnv.TIMEBASE_OAUTH2_TOKEN_PARAMS, '{"audience": "api"}'),
    ],
)
def test_interactive_mode_rejects_service_oauth_settings(
    monkeypatch: pytest.MonkeyPatch,
    env_var: str,
    value: str,
) -> None:
    monkeypatch.setenv(SettingsEnv.TIMEBASE_AUTH_MODE, "interactive")
    monkeypatch.setenv(env_var, value)

    with pytest.raises(ValidationError, match="interactive"):
        MCPSettings()


@pytest.mark.parametrize(
    "host",
    ["0.0.0.0", "127.0.0.1"],
)
def test_interactive_mode_rejected_on_http_transport(
    monkeypatch: pytest.MonkeyPatch,
    host: str,
) -> None:
    monkeypatch.setenv(SettingsEnv.TIMEBASE_AUTH_MODE, "interactive")
    monkeypatch.setenv(SettingsEnv.MCP_TRANSPORT, "streamable-http")
    monkeypatch.setenv(SettingsEnv.MCP_HOST, host)

    with pytest.raises(ValidationError, match="stdio transport"):
        MCPSettings()


@pytest.mark.parametrize("mode", ["none", "forward_identity", "interactive"])
def test_explicit_non_credential_auth_modes_reject_username(
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    monkeypatch.setenv(SettingsEnv.TIMEBASE_AUTH_MODE, mode)
    monkeypatch.setenv(SettingsEnv.TIMEBASE_USERNAME, "u")

    if mode == "forward_identity":
        monkeypatch.setenv(SettingsEnv.MCP_AUTH_AUDIENCE, "timebase-api")
        monkeypatch.setenv(
            SettingsEnv.MCP_AUTH_PUBLIC_URL, "https://mcp.example.com/mcp"
        )
        monkeypatch.setenv(SettingsEnv.MCP_TRANSPORT, "streamable-http")

    with pytest.raises(ValidationError, match="cannot be combined|both be set"):
        MCPSettings()


def test_explicit_auto_allows_basic_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(SettingsEnv.TIMEBASE_AUTH_MODE, "auto")
    monkeypatch.setenv(SettingsEnv.TIMEBASE_USERNAME, "u")
    monkeypatch.setenv(SettingsEnv.TIMEBASE_PASSWORD, "p")

    settings = MCPSettings()

    server = settings.resolve_servers()[0]
    assert server.auth_mode == "auto"
    assert server.username == "u"
    assert server.password is not None
    assert server.password.get_secret_value() == "p"


def test_explicit_auto_allows_oauth2_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(SettingsEnv.TIMEBASE_AUTH_MODE, "auto")
    monkeypatch.setenv(
        SettingsEnv.TIMEBASE_OAUTH2_TOKEN_URL, "https://idp.example/token"
    )
    monkeypatch.setenv(SettingsEnv.TIMEBASE_OAUTH2_CLIENT_ID, "client-id")
    monkeypatch.setenv(SettingsEnv.TIMEBASE_OAUTH2_CLIENT_SECRET, "client-secret")

    settings = MCPSettings()

    server = settings.resolve_servers()[0]
    assert server.auth_mode == "auto"
    assert server.oauth2_token_url == "https://idp.example/token"


def test_explicit_auto_allows_interactive_oauth_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(SettingsEnv.TIMEBASE_AUTH_MODE, "auto")
    monkeypatch.setenv(SettingsEnv.TIMEBASE_OAUTH2_CLIENT_ID, "interactive-client")
    monkeypatch.setenv(SettingsEnv.TIMEBASE_OAUTH2_SCOPE, "openid profile")

    settings = MCPSettings()
    server = settings.resolve_servers()[0]

    assert server.auth_mode == "auto"
    assert server.oauth2_client_id == "interactive-client"
    assert server.oauth2_scope == "openid profile"


def test_auth_mode_none_rejects_password(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(SettingsEnv.TIMEBASE_AUTH_MODE, "none")
    monkeypatch.setenv(SettingsEnv.TIMEBASE_USERNAME, "u")
    monkeypatch.setenv(SettingsEnv.TIMEBASE_PASSWORD, "p")

    with pytest.raises(ValidationError, match="cannot be combined"):
        MCPSettings()


def test_forward_identity_rejects_api_keys_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(SettingsEnv.TIMEBASE_AUTH_MODE, "forward_identity")
    monkeypatch.setenv(SettingsEnv.MCP_TRANSPORT, "streamable-http")
    monkeypatch.setenv(SettingsEnv.MCP_AUTH_AUDIENCE, "timebase-api")
    monkeypatch.setenv(SettingsEnv.MCP_AUTH_API_KEYS_FILE, "/var/run/keys.json")

    with pytest.raises(ValidationError, match="forward_identity"):
        MCPSettings()
