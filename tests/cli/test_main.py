import errno
import importlib
import json
import logging
import sys
from pathlib import Path
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
    monkeypatch.setenv(SettingsEnv.TIMEBASE_PASSWORD, "credential-log-password")
    monkeypatch.setenv(
        SettingsEnv.TIMEBASE_OAUTH2_TOKEN_URL, "https://idp.example/token"
    )
    monkeypatch.setenv(SettingsEnv.TIMEBASE_OAUTH2_CLIENT_ID, "client-id")
    monkeypatch.setenv(
        SettingsEnv.TIMEBASE_OAUTH2_CLIENT_SECRET, "credential-log-client-secret"
    )
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
    assert "credential-log-password" not in caplog.text
    assert '"tb_oauth2_client_secret": "**********"' in caplog.text
    assert "credential-log-client-secret" not in caplog.text
    assert '"tb_oauth2_token_url": "https://idp.example/token"' in caplog.text
    assert '"log_level": "debug"' in caplog.text
    assert "Env diagnostics:" not in caplog.text


@pytest.mark.parametrize(
    "environment",
    [
        {SettingsEnv.TIMEBASE_PASSWORD: "credential-log-secret"},
        {SettingsEnv.TIMEBASE_OAUTH2_CLIENT_SECRET: "credential-log-secret"},
        {
            SettingsEnv.TIMEBASE_OAUTH2_TOKEN_PARAMS: json.dumps(
                {"client_secret": "credential-log-secret"}
            )
        },
        {SettingsEnv.TIMEBASE_WEBADMIN_PASSWORD: "credential-log-secret"},
        {SettingsEnv.TIMEBASE_WEBADMIN_CLIENT_SECRET: "credential-log-secret"},
        {SettingsEnv.TIMEBASE_WEBADMIN_API_SECRET: "credential-log-secret"},
        {
            SettingsEnv.TIMEBASE_SERVERS: json.dumps(
                [
                    {
                        "url": "dxtick://localhost:8011",
                        "password": "credential-log-secret",
                    }
                ]
            )
        },
    ],
)
def test_load_settings_errors_do_not_expose_credentials(
    environment: dict[str, str],
    server_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    for name, value in environment.items():
        monkeypatch.setenv(name, value)

    with caplog.at_level(logging.ERROR), pytest.raises(ConfigurationError):
        server_module.load_settings()

    assert "Invalid TimeBase MCP configuration:" in caplog.text
    assert "credential-log-secret" not in caplog.text


@pytest.mark.parametrize(
    "variable",
    [
        SettingsEnv.TIMEBASE_URL,
        SettingsEnv.TIMEBASE_HTTP_URL,
        SettingsEnv.TIMEBASE_OAUTH2_TOKEN_URL,
        SettingsEnv.TIMEBASE_WEBADMIN_URL,
        SettingsEnv.TIMEBASE_WEBADMIN_ISSUER_URL,
        SettingsEnv.TIMEBASE_WEBADMIN_REDIRECT_URI,
        SettingsEnv.TIMEBASE_WEBADMIN_TOKEN_URL,
        SettingsEnv.MCP_AUTH_ISSUER_URL,
        SettingsEnv.MCP_AUTH_JWKS_URL,
        SettingsEnv.MCP_AUTH_PUBLIC_URL,
    ],
)
def test_load_settings_sanitizes_urls_in_error_diagnostics(
    variable: str,
    server_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv(
        variable,
        "https://user:private-url-password@diagnostic.example/context"
        "?token=private-url-query#private-url-fragment",
    )
    monkeypatch.setenv(SettingsEnv.MCP_PORT, "invalid")

    with caplog.at_level(logging.ERROR), pytest.raises(ConfigurationError):
        server_module.load_settings()

    assert "https://diagnostic.example/context" in caplog.text
    for secret in ("private-url-password", "private-url-query", "private-url-fragment"):
        assert secret not in caplog.text


@pytest.mark.parametrize(
    ("environment", "message"),
    [
        (
            {
                SettingsEnv.TIMEBASE_HTTP_URL: (
                    "https://reader:123/private-url-secret@monitor.example/context"
                ),
                SettingsEnv.MCP_PORT: "invalid",
            },
            "MCP_PORT",
        ),
        (
            {SettingsEnv.TIMEBASE_WEBADMIN_URL: "http://[u:private-url-secret]"},
            "webadmin_url must be an HTTP(S) URL",
        ),
        (
            {
                SettingsEnv.TIMEBASE_SERVERS: json.dumps(
                    [{"url": "dxtick://u:private-url-secret@", "auth_mode": "basic"}]
                )
            },
            "basic auth requires username and password",
        ),
        (
            {SettingsEnv.TIMEBASE_SERVERS: "https://u:private-url-secret@example/file"},
            "Cannot read TIMEBASE_SERVERS file",
        ),
        (
            {
                SettingsEnv.MCP_TRANSPORT: "streamable-http",
                SettingsEnv.MCP_HOST: "0.0.0.0",
                SettingsEnv.MCP_AUTH_AUDIENCE: "timebase-api",
                SettingsEnv.MCP_AUTH_PUBLIC_URL: "https://[u:private-url-secret]",
            },
            "MCP_AUTH_PUBLIC_URL must use HTTPS",
        ),
    ],
)
def test_load_settings_rejects_invalid_urls_without_exposing_them(
    environment: dict[str, str],
    message: str,
    server_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    for name, value in environment.items():
        monkeypatch.setenv(name, value)

    with caplog.at_level(logging.ERROR), pytest.raises(ConfigurationError):
        server_module.load_settings()

    assert message in caplog.text
    assert "private-url-secret" not in caplog.text


@pytest.mark.parametrize(
    "redirect_uri",
    [
        "https://u:private-url-secret@localhost/callback",
        "http://localhost:private-url-secret/callback",
    ],
)
def test_load_settings_redirect_errors_do_not_expose_input(
    redirect_uri: str,
    server_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv(SettingsEnv.TIMEBASE_WEBADMIN_URL, "https://webadmin.example")
    monkeypatch.setenv(SettingsEnv.TIMEBASE_WEBADMIN_AUTH_MODE, "interactive")
    monkeypatch.setenv(SettingsEnv.TIMEBASE_WEBADMIN_CLIENT_ID, "client")
    monkeypatch.setenv(SettingsEnv.TIMEBASE_WEBADMIN_ISSUER_URL, "https://idp.example")
    monkeypatch.setenv(SettingsEnv.TIMEBASE_WEBADMIN_SCOPE, "webadmin.read")
    monkeypatch.setenv(SettingsEnv.TIMEBASE_WEBADMIN_REDIRECT_URI, redirect_uri)

    with caplog.at_level(logging.ERROR), pytest.raises(ConfigurationError):
        server_module.load_settings()

    assert "Interactive OAuth redirect URI" in caplog.text
    assert "private-url-secret" not in caplog.text


@pytest.mark.parametrize(
    "server",
    [
        {"url": "dxtick://localhost:8011", "password": "private-url-secret"},
        {"url": "dxtick://u:private-url-secret@", "auth_mode": "basic"},
    ],
)
def test_servers_print_errors_do_not_expose_credentials(
    server: dict[str, str], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from timebase_mcp.cli.app import main

    path = tmp_path / "servers.json"
    path.write_text(json.dumps([server]))

    assert main(["servers-print", str(path)]) == 1

    output = capsys.readouterr()
    assert "basic auth requires username and password" in output.err
    assert "private-url-secret" not in output.err + output.out


@pytest.mark.parametrize(
    ("error_number", "reason"),
    [
        (errno.ENOENT, "No such file or directory"),
        (errno.EACCES, "Permission denied"),
    ],
)
def test_server_file_errors_keep_the_reason_without_exposing_the_path(
    error_number: int,
    reason: str,
    server_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from timebase_mcp.cli.app import main

    path = tmp_path / "private-file-password.json"

    def fail_read(path: Path, **_kwargs: object) -> str:
        raise OSError(error_number, reason, str(path))

    monkeypatch.setattr(Path, "read_text", fail_read)
    monkeypatch.setenv(SettingsEnv.TIMEBASE_SERVERS, str(path))

    with caplog.at_level(logging.ERROR), pytest.raises(ConfigurationError):
        server_module.load_settings()
    assert main(["servers-print", str(path)]) == 1

    output = capsys.readouterr()
    assert reason in caplog.text
    assert reason in output.err
    assert "private-file-password" not in caplog.text + output.err + output.out
    assert str(path) not in caplog.text + output.err + output.out


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
