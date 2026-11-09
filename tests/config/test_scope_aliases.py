import json

import pytest
from pydantic import ValidationError

from timebase_mcp.config.env import SettingsEnv
from timebase_mcp.config.settings import MCPSettings

FULL_SCOPE = "https://mcp.example.com/mcp/mcp.access"


@pytest.fixture
def alias_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(SettingsEnv.MCP_TRANSPORT, "streamable-http")
    monkeypatch.setenv(SettingsEnv.MCP_AUTH_AUDIENCE, "shared-api-guid")
    monkeypatch.setenv(SettingsEnv.MCP_AUTH_REQUIRED_SCOPES, FULL_SCOPE)
    monkeypatch.setenv(
        SettingsEnv.MCP_AUTH_SCOPE_ALIASES,
        json.dumps({FULL_SCOPE: "mcp.access"}),
    )


def test_alias_environment_preserves_forwarding_and_plain_native_transport(
    alias_environment: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(SettingsEnv.TIMEBASE_URL, "dxtick://internal-timebase:8011")
    monkeypatch.setenv(SettingsEnv.TIMEBASE_AUTH_MODE, "forward_identity")

    settings = MCPSettings()

    assert settings.auth_scope_aliases == {FULL_SCOPE: "mcp.access"}
    assert settings.auth_required_scopes == [FULL_SCOPE]
    assert settings.inbound_auth_mode == "jwt"
    server = settings.resolve_servers()[0]
    assert server.auth_mode == "forward_identity"
    assert server.url == "dxtick://internal-timebase:8011"


@pytest.mark.parametrize(
    "raw_aliases",
    [
        "not JSON",
        "[]",
        "null",
        '"mcp.access"',
        json.dumps({FULL_SCOPE: 1}),
        json.dumps({FULL_SCOPE: ["mcp.access"]}),
        json.dumps({FULL_SCOPE: ""}),
    ],
)
def test_scope_aliases_reject_invalid_json_or_scope_tokens(
    alias_environment: None,
    monkeypatch: pytest.MonkeyPatch,
    raw_aliases: str,
) -> None:
    monkeypatch.setenv(SettingsEnv.MCP_AUTH_SCOPE_ALIASES, raw_aliases)

    with pytest.raises(
        ValidationError,
        match="auth_scope_aliases|MCP_AUTH_SCOPE_ALIASES",
    ):
        MCPSettings()


def test_scope_alias_key_must_be_a_valid_scope_token(
    alias_environment: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invalid_scope = "api/non-ascii-\u00e9"
    monkeypatch.setenv(SettingsEnv.MCP_AUTH_REQUIRED_SCOPES, invalid_scope)
    monkeypatch.setenv(
        SettingsEnv.MCP_AUTH_SCOPE_ALIASES,
        json.dumps({invalid_scope: "mcp.access"}),
    )

    with pytest.raises(ValidationError, match="single nonempty ASCII scope tokens"):
        MCPSettings()


def test_scope_alias_key_must_be_required(
    alias_environment: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(SettingsEnv.MCP_AUTH_REQUIRED_SCOPES, "other.permission")

    with pytest.raises(ValidationError, match="MCP_AUTH_REQUIRED_SCOPES"):
        MCPSettings()


@pytest.mark.parametrize(
    ("name", "value"),
    [
        (SettingsEnv.MCP_TRANSPORT, "stdio"),
        (SettingsEnv.MCP_AUTH_AUDIENCE, ""),
        (SettingsEnv.MCP_AUTH_API_KEYS_FILE, "/unused/keys.json"),
    ],
)
def test_nonempty_aliases_require_http_jwt_authentication(
    alias_environment: None,
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    value: str,
) -> None:
    monkeypatch.setenv(name, value)

    with pytest.raises(ValidationError, match="MCP_AUTH_SCOPE_ALIASES requires"):
        MCPSettings()


def test_empty_aliases_preserve_existing_authentication_modes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert MCPSettings().auth_scope_aliases == {}

    monkeypatch.setenv(SettingsEnv.MCP_AUTH_SCOPE_ALIASES, "{}")
    monkeypatch.setenv(SettingsEnv.MCP_TRANSPORT, "streamable-http")
    monkeypatch.setenv(SettingsEnv.MCP_AUTH_API_KEYS_FILE, "/unused/keys.json")

    settings = MCPSettings()
    assert settings.auth_scope_aliases == {}
    assert settings.inbound_auth_mode == "api_key"
