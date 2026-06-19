import importlib
import logging
import sys
from types import ModuleType
from unittest.mock import Mock

import pytest

from timebase_mcp.config import SettingsEnv


@pytest.fixture
def main_module(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    monkeypatch.setattr(sys, "argv", ["timebase-mcp"])
    module = importlib.import_module("timebase_mcp.main")
    return importlib.reload(module)


def test_run_server_logs_redacted_configuration_at_debug(
    main_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    settings = main_module.MCPSettings(
        tb_username="alice",
        tb_password="secret",
        log_level="DEBUG",
    )
    fake_server = Mock()
    fake_server.run.side_effect = KeyboardInterrupt()

    monkeypatch.setattr(main_module, "load_settings", lambda: settings)
    monkeypatch.setattr(main_module, "build_server", lambda settings=None: fake_server)
    monkeypatch.setattr(main_module, "_should_log_terminal_status", lambda: False)

    with caplog.at_level(logging.DEBUG):
        exit_code = main_module.run_server()

    assert exit_code == 130
    assert "TimeBase MCP configuration:" in caplog.text
    assert '"tb_password": "**********"' in caplog.text
    assert '"tb_password": "secret"' not in caplog.text


def test_run_server_does_not_log_configuration_at_info(
    main_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    settings = main_module.MCPSettings(
        tb_username="alice",
        tb_password="secret",
        log_level="INFO",
    )
    fake_server = Mock()
    fake_server.run.side_effect = KeyboardInterrupt()

    monkeypatch.setattr(main_module, "load_settings", lambda: settings)
    monkeypatch.setattr(main_module, "build_server", lambda settings=None: fake_server)
    monkeypatch.setattr(main_module, "_should_log_terminal_status", lambda: False)

    with caplog.at_level(logging.DEBUG):
        exit_code = main_module.run_server()

    assert exit_code == 130
    assert "TimeBase MCP configuration:" not in caplog.text


def test_run_server_warns_for_unlimited_remote_http(
    main_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    settings = main_module.MCPSettings(
        transport="streamable-http",
        host="0.0.0.0",
        auth_api_keys_file="/var/run/keys.json",
        max_concurrent_ops=0,
    )
    fake_server = Mock()
    fake_server.run.side_effect = KeyboardInterrupt()

    monkeypatch.setattr(main_module, "load_settings", lambda: settings)
    monkeypatch.setattr(main_module, "build_server", lambda settings=None: fake_server)

    with caplog.at_level(logging.WARNING):
        exit_code = main_module.run_server()

    assert exit_code == 130
    assert "MCP_MAX_CONCURRENT_OPS=0 disables admission control" in caplog.text


def test_run_server_does_not_warn_for_limited_remote_http(
    main_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    settings = main_module.MCPSettings(
        transport="streamable-http",
        host="0.0.0.0",
        auth_api_keys_file="/var/run/keys.json",
        max_concurrent_ops=10,
    )
    fake_server = Mock()
    fake_server.run.side_effect = KeyboardInterrupt()

    monkeypatch.setattr(main_module, "load_settings", lambda: settings)
    monkeypatch.setattr(main_module, "build_server", lambda settings=None: fake_server)

    with caplog.at_level(logging.WARNING):
        exit_code = main_module.run_server()

    assert exit_code == 130
    assert "MCP_MAX_CONCURRENT_OPS=0 disables admission control" not in caplog.text


def test_run_server_does_not_warn_for_stdio_unlimited_ops(
    main_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    settings = main_module.MCPSettings(max_concurrent_ops=0)
    fake_server = Mock()
    fake_server.run.side_effect = KeyboardInterrupt()

    monkeypatch.setattr(main_module, "load_settings", lambda: settings)
    monkeypatch.setattr(main_module, "build_server", lambda settings=None: fake_server)
    monkeypatch.setattr(main_module, "_should_log_terminal_status", lambda: False)

    with caplog.at_level(logging.WARNING):
        exit_code = main_module.run_server()

    assert exit_code == 130
    assert "MCP_MAX_CONCURRENT_OPS=0 disables admission control" not in caplog.text


def test_load_settings_logs_redacted_configuration_on_validation_error(
    main_module: ModuleType,
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
            main_module.ConfigurationError,
            match="Invalid TimeBase MCP configuration.",
        ),
    ):
        main_module.load_settings()

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
    main_module: ModuleType,
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
        main_module.MCPSettings,
        "debug_log_payload_from_env",
        lambda: (_ for _ in ()).throw(TypeError("boom")),
    )

    with (
        caplog.at_level(logging.ERROR),
        pytest.raises(
            main_module.ConfigurationError,
            match="Invalid TimeBase MCP configuration.",
        ),
    ):
        main_module.load_settings()

    assert "Invalid TimeBase MCP configuration:" in caplog.text
    assert "Raw settings: <unavailable>" in caplog.text
