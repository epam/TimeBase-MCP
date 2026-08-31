from __future__ import annotations

import os

import pytest

from tests.auth.helpers import (
    advertise_oauth,
    forward_identity_settings,
    patch_auto_client_creation,
)
from timebase_mcp.clients.factory import create_timebase_client
from timebase_mcp.clients.native.common import connection_error_hint
from timebase_mcp.config.env import DXAPI_SSL_TERMINATION_ENV, SettingsEnv
from timebase_mcp.config.settings import MCPSettings
from timebase_mcp.errors import ConfigurationError
from timebase_mcp.runtime.instance import (
    TimeBaseInstanceConfig,
    TimeBaseInstanceRuntime,
)
from timebase_mcp.runtime.state import build_runtime


def test_auto_auth_switches_to_interactive_and_sets_ssl_termination(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(DXAPI_SSL_TERMINATION_ENV, raising=False)
    monkeypatch.setenv(SettingsEnv.TIMEBASE_URL, "dxtick://tb.example.com:8011")
    runtime = build_runtime(MCPSettings())
    captured_configs = patch_auto_client_creation(monkeypatch)
    advertise_oauth(monkeypatch)
    monkeypatch.setattr(
        "timebase_mcp.runtime.instance.TimeBaseInstanceRuntime.get_interactive_provider",
        lambda _instance: object(),
    )

    create_timebase_client(runtime.default_instance)

    assert captured_configs[0].auth_mode == "interactive"
    assert captured_configs[0].http_base_url == "https://tb.example.com:8011"
    assert runtime.default_instance.config.auth_mode == "interactive"
    assert os.environ[DXAPI_SSL_TERMINATION_ENV] == "true"


def test_auto_auth_passes_interactive_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(DXAPI_SSL_TERMINATION_ENV, raising=False)
    monkeypatch.setenv(SettingsEnv.TIMEBASE_URL, "dxtick://tb.example.com:8011")
    monkeypatch.setenv(SettingsEnv.TIMEBASE_OAUTH2_CLIENT_ID, "interactive-client")
    monkeypatch.setenv(SettingsEnv.TIMEBASE_OAUTH2_SCOPE, "openid profile")
    runtime = build_runtime(MCPSettings())
    captured_configs = patch_auto_client_creation(monkeypatch)
    advertise_oauth(monkeypatch)
    monkeypatch.setattr(
        "timebase_mcp.runtime.instance.TimeBaseInstanceRuntime.get_interactive_provider",
        lambda _instance: object(),
    )

    create_timebase_client(runtime.default_instance)

    assert captured_configs[0].auth_mode == "interactive"
    assert captured_configs[0].tb_oauth2_client_id == "interactive-client"
    assert captured_configs[0].tb_oauth2_scope == "openid profile"


def test_auto_auth_switches_to_forward_identity_for_remote_inbound_auth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(SettingsEnv.TIMEBASE_URL, "dxtick://tb.example.com:8011")
    runtime = build_runtime(forward_identity_settings())
    captured_configs = patch_auto_client_creation(monkeypatch)
    advertise_oauth(monkeypatch)

    create_timebase_client(runtime.default_instance)

    assert captured_configs[0].auth_mode == "forward_identity"
    assert runtime.default_instance.config.auth_mode == "forward_identity"


def test_auto_auth_rejects_api_key_inbound_forwarding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(SettingsEnv.TIMEBASE_URL, "dxtick://tb.example.com:8011")
    monkeypatch.setenv(SettingsEnv.MCP_TRANSPORT, "streamable-http")
    monkeypatch.setenv(SettingsEnv.MCP_HOST, "0.0.0.0")
    monkeypatch.setenv(SettingsEnv.MCP_AUTH_API_KEYS_FILE, "/var/run/keys.json")
    runtime = build_runtime(MCPSettings())
    patch_auto_client_creation(monkeypatch)
    advertise_oauth(monkeypatch)

    with pytest.raises(ConfigurationError, match="API-key callers cannot be forwarded"):
        create_timebase_client(runtime.default_instance)

    assert runtime.default_instance.config.auth_mode == "auto"


def test_auto_auth_rejects_remote_interactive_without_forwardable_jwt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(SettingsEnv.TIMEBASE_URL, "dxtick://tb.example.com:8011")
    monkeypatch.setenv(SettingsEnv.MCP_TRANSPORT, "streamable-http")
    monkeypatch.setenv(SettingsEnv.MCP_HOST, "0.0.0.0")
    runtime = build_runtime(MCPSettings())
    patch_auto_client_creation(monkeypatch)
    advertise_oauth(monkeypatch)

    with pytest.raises(ConfigurationError, match="interactive login is only supported"):
        create_timebase_client(runtime.default_instance)

    assert runtime.default_instance.config.auth_mode == "auto"


def test_auto_auth_rejects_interactive_on_loopback_http(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(SettingsEnv.TIMEBASE_URL, "dxtick://tb.example.com:8011")
    monkeypatch.setenv(SettingsEnv.MCP_TRANSPORT, "streamable-http")
    runtime = build_runtime(MCPSettings())
    patch_auto_client_creation(monkeypatch)
    advertise_oauth(monkeypatch)

    with pytest.raises(ConfigurationError, match="interactive login is only supported"):
        create_timebase_client(runtime.default_instance)

    assert runtime.default_instance.config.auth_mode == "auto"


def test_auto_auth_switches_to_basic_when_credentials_are_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(SettingsEnv.TIMEBASE_AUTH_MODE, "auto")
    monkeypatch.setenv(SettingsEnv.TIMEBASE_USERNAME, "u")
    monkeypatch.setenv(SettingsEnv.TIMEBASE_PASSWORD, "p")
    runtime = build_runtime(MCPSettings())
    captured_configs = patch_auto_client_creation(monkeypatch)
    advertise_oauth(monkeypatch)

    create_timebase_client(runtime.default_instance)

    assert captured_configs[0].auth_mode == "basic"
    assert captured_configs[0].tb_username == "u"
    assert runtime.default_instance.config.auth_mode == "basic"


def test_auto_auth_switches_to_oauth2_when_client_credentials_are_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(SettingsEnv.TIMEBASE_AUTH_MODE, "auto")
    monkeypatch.setenv(
        SettingsEnv.TIMEBASE_OAUTH2_TOKEN_URL, "https://idp.example/token"
    )
    monkeypatch.setenv(SettingsEnv.TIMEBASE_OAUTH2_CLIENT_ID, "client-id")
    monkeypatch.setenv(SettingsEnv.TIMEBASE_OAUTH2_CLIENT_SECRET, "client-secret")
    runtime = build_runtime(MCPSettings())
    captured_configs = patch_auto_client_creation(monkeypatch)
    advertise_oauth(monkeypatch)

    create_timebase_client(runtime.default_instance)

    assert captured_configs[0].auth_mode == "oauth2_client_credentials"
    assert captured_configs[0].oauth2_config is not None
    assert runtime.default_instance.config.auth_mode == "oauth2_client_credentials"


def test_auto_auth_switches_to_none_when_discovery_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(SettingsEnv.TIMEBASE_URL, "dxtick://tb.example.com:8011")
    runtime = build_runtime(MCPSettings())
    captured_configs = patch_auto_client_creation(monkeypatch)

    def fail_discovery(**_kwargs):
        from timebase_mcp.errors import ConfigurationError

        raise ConfigurationError("not advertised")

    monkeypatch.setattr(
        "timebase_mcp.auth.outbound._resolve_interactive_endpoints",
        fail_discovery,
    )

    create_timebase_client(runtime.default_instance)

    assert captured_configs[0].auth_mode == "none"
    assert captured_configs[0].auto_auth_error == "not advertised"
    assert runtime.default_instance.config.auth_mode == "none"


def test_enterprise_auto_auth_hint_includes_discovery_failure() -> None:
    config = TimeBaseInstanceConfig(
        tb_url="dxtick://tb.example.com:8011",
        auth_mode="auto",
        auto_auth_error="Failed to fetch TimeBase OAuth metadata.",
    )
    instance = TimeBaseInstanceRuntime(
        key="default",
        config=config,
    )

    hint = connection_error_hint(
        instance,
        Exception("Handshake failed: Wrong username or password"),
        edition="enterprise",
    )

    assert "TIMEBASE_AUTH_MODE=interactive" in hint
    assert "OAuth auto-discovery failed earlier" in hint
