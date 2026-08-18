from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from timebase_mcp.auth import keystore
from timebase_mcp.auth.inbound import build_inbound_auth
from timebase_mcp.config.env import SettingsEnv
from timebase_mcp.config.settings import MCPSettings


def test_build_inbound_auth_disabled_returns_none() -> None:
    assert build_inbound_auth(MCPSettings()) is None


def test_inbound_http_auth_disabled_without_audience_or_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(SettingsEnv.MCP_TRANSPORT, "streamable-http")

    settings = MCPSettings()

    assert settings.inbound_auth_enabled is False
    assert build_inbound_auth(settings) is None


def test_remote_jwt_auth_requires_public_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(SettingsEnv.MCP_TRANSPORT, "streamable-http")
    monkeypatch.setenv(SettingsEnv.MCP_HOST, "0.0.0.0")
    monkeypatch.setenv(SettingsEnv.MCP_AUTH_AUDIENCE, "timebase-api")

    with pytest.raises(ValidationError, match="MCP_AUTH_PUBLIC_URL"):
        MCPSettings()


def test_remote_jwt_auth_requires_https_public_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(SettingsEnv.MCP_TRANSPORT, "streamable-http")
    monkeypatch.setenv(SettingsEnv.MCP_HOST, "0.0.0.0")
    monkeypatch.setenv(SettingsEnv.MCP_AUTH_AUDIENCE, "timebase-api")
    monkeypatch.setenv(SettingsEnv.MCP_AUTH_PUBLIC_URL, "http://mcp.example.com/mcp")

    with pytest.raises(ValidationError, match="MCP_AUTH_PUBLIC_URL"):
        MCPSettings()


def test_remote_jwt_auth_accepts_https_public_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(SettingsEnv.MCP_TRANSPORT, "streamable-http")
    monkeypatch.setenv(SettingsEnv.MCP_HOST, "0.0.0.0")
    monkeypatch.setenv(SettingsEnv.MCP_AUTH_AUDIENCE, "timebase-api")
    monkeypatch.setenv(SettingsEnv.MCP_AUTH_PUBLIC_URL, "https://mcp.example.com/mcp")

    settings = MCPSettings()

    assert settings.inbound_auth_mode == "jwt"
    assert settings.auth_public_url == "https://mcp.example.com/mcp"


@pytest.mark.anyio
async def test_build_inbound_auth_with_api_keys_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    record, raw_key = keystore.build_record(name="alice", scopes=["timebase.read"])
    keys_file = tmp_path / "keys.json"
    keystore.write_store(keys_file, [record])

    monkeypatch.setenv(SettingsEnv.MCP_TRANSPORT, "streamable-http")
    monkeypatch.setenv(SettingsEnv.MCP_AUTH_API_KEYS_FILE, str(keys_file))

    inbound = build_inbound_auth(MCPSettings())

    assert inbound is not None
    assert inbound.auth_settings.resource_server_url is None
    assert await inbound.token_verifier.verify_token(raw_key) is not None
    assert await inbound.token_verifier.verify_token("tbk_unknown") is None


def test_inbound_auth_disabled_for_stdio_default() -> None:
    settings = MCPSettings()  # transport defaults to stdio

    assert settings.inbound_auth_enabled is False


def test_inbound_auth_disabled_for_loopback_http(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(SettingsEnv.MCP_TRANSPORT, "streamable-http")
    # MCP_HOST defaults to 127.0.0.1

    settings = MCPSettings()

    assert settings.inbound_auth_enabled is False


def test_inbound_auth_enabled_for_nonloopback_http(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(SettingsEnv.MCP_TRANSPORT, "streamable-http")
    monkeypatch.setenv(SettingsEnv.MCP_HOST, "0.0.0.0")
    # Provide a keys file path so the validator doesn't require MCP_AUTH_AUDIENCE
    monkeypatch.setenv(SettingsEnv.MCP_AUTH_API_KEYS_FILE, "/var/run/keys.json")

    settings = MCPSettings()

    assert settings.inbound_auth_enabled is True


def test_inbound_auth_disabled_without_auth_config_on_remote(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(SettingsEnv.MCP_TRANSPORT, "streamable-http")
    monkeypatch.setenv(SettingsEnv.MCP_HOST, "0.0.0.0")

    settings = MCPSettings()

    assert settings.inbound_auth_enabled is False
    assert build_inbound_auth(settings) is None


def test_inbound_auth_enabled_on_loopback_with_audience(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(SettingsEnv.MCP_TRANSPORT, "streamable-http")
    monkeypatch.setenv(SettingsEnv.MCP_AUTH_AUDIENCE, "timebase-api")

    settings = MCPSettings()

    assert settings.inbound_auth_enabled is True
    assert settings.inbound_auth_mode == "jwt"
