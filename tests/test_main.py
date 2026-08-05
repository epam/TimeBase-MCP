import importlib
import logging
import sys
from types import ModuleType
from unittest.mock import Mock

import pytest
from pydantic.types import SecretStr

from timebase_mcp.config.env import SettingsEnv
from timebase_mcp.config.settings import MCPSettings
from timebase_mcp.errors import ConfigurationError


@pytest.fixture
def server_module(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    monkeypatch.setattr(sys, "argv", ["timebase-mcp"])
    module = importlib.import_module("timebase_mcp.cli.server")
    return importlib.reload(module)


def test_run_server_logs_redacted_configuration_at_debug(
    server_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    settings = MCPSettings(
        tb_username="alice",
        tb_password=SecretStr("secret"),
        log_level="DEBUG",
    )
    fake_server = Mock()
    fake_server.run.side_effect = KeyboardInterrupt()

    monkeypatch.setattr(server_module, "load_settings", lambda: settings)
    monkeypatch.setattr(
        server_module, "build_server", lambda settings=None: fake_server
    )
    monkeypatch.setattr(server_module, "should_log_terminal_status", lambda: False)

    with caplog.at_level(logging.DEBUG):
        exit_code = server_module.run_server()

    assert exit_code == 130
    assert "TimeBase MCP configuration:" in caplog.text
    assert '"tb_password": "**********"' in caplog.text
    assert '"tb_password": "secret"' not in caplog.text


def test_run_server_does_not_log_configuration_at_info(
    server_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    settings = MCPSettings(
        tb_username="alice",
        tb_password=SecretStr("secret"),
        log_level="INFO",
    )
    fake_server = Mock()
    fake_server.run.side_effect = KeyboardInterrupt()

    monkeypatch.setattr(server_module, "load_settings", lambda: settings)
    monkeypatch.setattr(
        server_module, "build_server", lambda settings=None: fake_server
    )
    monkeypatch.setattr(server_module, "should_log_terminal_status", lambda: False)

    with caplog.at_level(logging.DEBUG):
        exit_code = server_module.run_server()

    assert exit_code == 130
    assert "TimeBase MCP configuration:" not in caplog.text


def test_run_server_warns_for_unlimited_remote_http(
    server_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    settings = MCPSettings(
        transport="streamable-http",
        host="0.0.0.0",
        auth_api_keys_file="/var/run/keys.json",
        max_concurrent_ops=0,
    )
    fake_server = Mock()
    fake_server.run.side_effect = KeyboardInterrupt()

    monkeypatch.setattr(server_module, "load_settings", lambda: settings)
    monkeypatch.setattr(
        server_module, "build_server", lambda settings=None: fake_server
    )

    with caplog.at_level(logging.WARNING):
        exit_code = server_module.run_server()

    assert exit_code == 130
    assert "MCP_MAX_CONCURRENT_OPS=0 disables admission control" in caplog.text


def test_run_server_does_not_warn_for_limited_remote_http(
    server_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    settings = MCPSettings(
        transport="streamable-http",
        host="0.0.0.0",
        auth_api_keys_file="/var/run/keys.json",
        max_concurrent_ops=10,
    )
    fake_server = Mock()
    fake_server.run.side_effect = KeyboardInterrupt()

    monkeypatch.setattr(server_module, "load_settings", lambda: settings)
    monkeypatch.setattr(
        server_module, "build_server", lambda settings=None: fake_server
    )

    with caplog.at_level(logging.WARNING):
        exit_code = server_module.run_server()

    assert exit_code == 130
    assert "MCP_MAX_CONCURRENT_OPS=0 disables admission control" not in caplog.text


def test_run_server_warns_for_remote_http_without_allowed_hosts(
    server_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    settings = MCPSettings(
        transport="streamable-http",
        host="0.0.0.0",
        auth_api_keys_file="/var/run/keys.json",
        max_concurrent_ops=10,
    )
    fake_server = Mock()
    fake_server.run.side_effect = KeyboardInterrupt()

    monkeypatch.setattr(server_module, "load_settings", lambda: settings)
    monkeypatch.setattr(
        server_module, "build_server", lambda settings=None: fake_server
    )

    with caplog.at_level(logging.WARNING):
        exit_code = server_module.run_server()

    assert exit_code == 130
    assert "MCP_ALLOWED_HOSTS/MCP_ALLOWED_ORIGINS are unset" in caplog.text


def test_run_server_does_not_warn_when_allowed_hosts_configured(
    server_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    settings = MCPSettings(
        transport="streamable-http",
        host="0.0.0.0",
        auth_api_keys_file="/var/run/keys.json",
        max_concurrent_ops=10,
        allowed_hosts=["mcp.example.com"],
    )
    fake_server = Mock()
    fake_server.run.side_effect = KeyboardInterrupt()

    monkeypatch.setattr(server_module, "load_settings", lambda: settings)
    monkeypatch.setattr(
        server_module, "build_server", lambda settings=None: fake_server
    )

    with caplog.at_level(logging.WARNING):
        exit_code = server_module.run_server()

    assert exit_code == 130
    assert "MCP_ALLOWED_HOSTS/MCP_ALLOWED_ORIGINS are unset" not in caplog.text


def test_run_server_passes_transport_security_to_http_run(
    server_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = MCPSettings(
        transport="streamable-http",
        host="0.0.0.0",
        auth_api_keys_file="/var/run/keys.json",
        allowed_hosts=["mcp.example.com"],
        allowed_origins=["https://mcp.example.com"],
    )
    fake_server = Mock()
    fake_server.run.side_effect = KeyboardInterrupt()

    monkeypatch.setattr(server_module, "load_settings", lambda: settings)
    monkeypatch.setattr(
        server_module, "build_server", lambda settings=None: fake_server
    )

    exit_code = server_module.run_server()

    assert exit_code == 130
    _, run_kwargs = fake_server.run.call_args
    transport_security = run_kwargs["transport_security"]
    assert transport_security.allowed_hosts == ["mcp.example.com"]
    assert transport_security.allowed_origins == ["https://mcp.example.com"]


def test_run_server_does_not_warn_for_stdio_unlimited_ops(
    server_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    settings = MCPSettings(max_concurrent_ops=0)
    fake_server = Mock()
    fake_server.run.side_effect = KeyboardInterrupt()

    monkeypatch.setattr(server_module, "load_settings", lambda: settings)
    monkeypatch.setattr(
        server_module, "build_server", lambda settings=None: fake_server
    )
    monkeypatch.setattr(server_module, "should_log_terminal_status", lambda: False)

    with caplog.at_level(logging.WARNING):
        exit_code = server_module.run_server()

    assert exit_code == 130
    assert "MCP_MAX_CONCURRENT_OPS=0 disables admission control" not in caplog.text


def test_load_settings_logs_redacted_configuration_on_validation_error(
    server_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv(SettingsEnv.TIMEBASE_USERNAME, "service-user")
    monkeypatch.setenv(SettingsEnv.TIMEBASE_PASSWORD, "secret")
    monkeypatch.setenv(
        SettingsEnv.TIMEBASE_OAUTH2_TOKEN_URL, "https://idp.example/token"
    )
    monkeypatch.setenv(SettingsEnv.TIMEBASE_OAUTH2_CLIENT_ID, "client-id")
    monkeypatch.setenv(SettingsEnv.TIMEBASE_OAUTH2_CLIENT_SECRET, "client-secret")
    monkeypatch.setenv(SettingsEnv.MCP_LOG_LEVEL, "debug")

    with (
        caplog.at_level(logging.ERROR),
        pytest.raises(
            ConfigurationError,
            match="Invalid TimeBase MCP configuration.",
        ),
    ):
        server_module.load_settings()

    assert "Invalid TimeBase MCP configuration:" in caplog.text
    assert '"tb_username": "service-user"' in caplog.text
    assert '"tb_password": "**********"' in caplog.text
    assert '"tb_password": "secret"' not in caplog.text
    assert '"tb_oauth2_client_secret": "**********"' in caplog.text
    assert '"tb_oauth2_client_secret": "client-secret"' not in caplog.text
    assert '"tb_oauth2_token_url": "https://idp.example/token"' in caplog.text
    assert '"log_level": "debug"' in caplog.text
    assert "Env diagnostics:" not in caplog.text


def test_load_settings_keeps_configuration_error_when_payload_rendering_fails(
    server_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv(SettingsEnv.TIMEBASE_USERNAME, "service-user")
    monkeypatch.setenv(SettingsEnv.TIMEBASE_PASSWORD, "secret")
    monkeypatch.setenv(
        SettingsEnv.TIMEBASE_OAUTH2_TOKEN_URL, "https://idp.example/token"
    )
    monkeypatch.setenv(SettingsEnv.TIMEBASE_OAUTH2_CLIENT_ID, "client-id")
    monkeypatch.setenv(SettingsEnv.TIMEBASE_OAUTH2_CLIENT_SECRET, "client-secret")
    monkeypatch.setattr(
        MCPSettings,
        "debug_log_payload_from_env",
        lambda: (_ for _ in ()).throw(TypeError("boom")),
    )

    with (
        caplog.at_level(logging.ERROR),
        pytest.raises(
            ConfigurationError,
            match="Invalid TimeBase MCP configuration.",
        ),
    ):
        server_module.load_settings()

    assert "Invalid TimeBase MCP configuration:" in caplog.text
    assert "Raw settings: <unavailable>" in caplog.text
