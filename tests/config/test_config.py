import json

import pytest
from pydantic import SecretStr, ValidationError

from timebase_mcp.config.env import SettingsEnv
from timebase_mcp.config.settings import MCPSettings
from timebase_mcp.config.webadmin import WebAdminAuthConfig, WebAdminConfig
from timebase_mcp.constants import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    DEFAULT_TIMEBASE_URL,
    DEFAULT_TRANSPORT,
)
from timebase_mcp.runtime.state import build_runtime


def test_settings_use_defaults_when_environment_is_not_set() -> None:
    settings = MCPSettings()

    assert settings.tb_url == DEFAULT_TIMEBASE_URL
    assert settings.tb_username is None
    assert settings.tb_password is None
    assert settings.tb_oauth2_token_url is None
    assert settings.tb_oauth2_client_id is None
    assert settings.tb_oauth2_client_secret is None
    assert settings.tb_oauth2_scope is None
    assert settings.tb_oauth2_token_params is None
    assert settings.oauth2_config is None
    assert settings.uses_oauth2 is False
    assert settings.detected_edition is None
    assert settings.webadmin.url is None
    assert settings.webadmin.auth.username is None
    assert settings.webadmin.auth.password is None
    assert settings.webadmin.auth.client_id is None
    assert settings.webadmin.auth.client_secret is None
    assert settings.transport == DEFAULT_TRANSPORT
    assert settings.host == DEFAULT_HOST
    assert settings.port == DEFAULT_PORT
    assert settings.log_level == "INFO"
    assert settings.max_concurrent_ops == 0
    assert settings.max_idle_clients == 0
    assert settings.operation_timeout_seconds == 60
    assert settings.allowed_hosts is None
    assert settings.allowed_origins is None
    assert settings.transport_security is None


def test_settings_parse_allowed_hosts_and_origins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        SettingsEnv.MCP_ALLOWED_HOSTS, "mcp.example.com, other.example.com:443"
    )
    monkeypatch.setenv(SettingsEnv.MCP_ALLOWED_ORIGINS, "https://mcp.example.com")

    settings = MCPSettings()

    assert settings.allowed_hosts == ["mcp.example.com", "other.example.com:443"]
    assert settings.allowed_origins == ["https://mcp.example.com"]

    security = settings.transport_security
    assert security is not None
    assert security.enable_dns_rebinding_protection is True
    assert security.allowed_hosts == ["mcp.example.com", "other.example.com:443"]
    assert security.allowed_origins == ["https://mcp.example.com"]


def test_settings_transport_security_enabled_with_only_one_list_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(SettingsEnv.MCP_ALLOWED_HOSTS, "mcp.example.com")

    settings = MCPSettings()

    security = settings.transport_security
    assert security is not None
    assert security.allowed_hosts == ["mcp.example.com"]
    assert security.allowed_origins == []


def test_settings_raise_validation_error_for_invalid_allowed_hosts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(SettingsEnv.MCP_ALLOWED_HOSTS, "[1, 2]")

    with pytest.raises(ValidationError, match="MCP_ALLOWED_HOSTS"):
        MCPSettings()


def test_settings_parse_environment_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(SettingsEnv.TIMEBASE_URL, "dxtick://timebase.example:8011")
    monkeypatch.setenv(SettingsEnv.TIMEBASE_USERNAME, "alice")
    monkeypatch.setenv(SettingsEnv.TIMEBASE_PASSWORD, "secret")
    monkeypatch.setenv(SettingsEnv.MCP_TRANSPORT, "streamable-http")
    monkeypatch.setenv(SettingsEnv.MCP_HOST, "0.0.0.0")
    monkeypatch.setenv(SettingsEnv.MCP_PORT, "8080")
    monkeypatch.setenv(SettingsEnv.MCP_LOG_LEVEL, "debug")
    monkeypatch.setenv(SettingsEnv.MCP_MAX_CONCURRENT_OPS, "4")
    monkeypatch.setenv(SettingsEnv.MCP_MAX_IDLE_CLIENTS, "3")
    monkeypatch.setenv(SettingsEnv.MCP_OPERATION_TIMEOUT_SECONDS, "30")
    monkeypatch.setenv(SettingsEnv.TIMEBASE_WEBADMIN_URL, "http://localhost:8099/")
    monkeypatch.setenv(SettingsEnv.TIMEBASE_WEBADMIN_USERNAME, "webadmin-user")
    monkeypatch.setenv(SettingsEnv.TIMEBASE_WEBADMIN_PASSWORD, "webadmin-password")
    monkeypatch.setenv(SettingsEnv.TIMEBASE_WEBADMIN_CLIENT_ID, "web")
    monkeypatch.setenv(SettingsEnv.TIMEBASE_WEBADMIN_CLIENT_SECRET, "secret")

    settings = MCPSettings()

    assert settings.tb_url == "dxtick://timebase.example:8011"
    assert settings.tb_username == "alice"
    assert settings.tb_password is not None
    assert settings.tb_password.get_secret_value() == "secret"
    assert settings.detected_edition is None
    assert settings.transport == "streamable-http"
    assert settings.host == "0.0.0.0"
    assert settings.port == 8080
    assert settings.log_level == "DEBUG"
    assert settings.max_concurrent_ops == 4
    assert settings.max_idle_clients == 3
    assert settings.operation_timeout_seconds == 30
    server = settings.resolve_servers()[0]
    assert server.webadmin.url == "http://localhost:8099"
    assert server.webadmin.auth.username == "webadmin-user"
    assert server.webadmin.auth.password is not None
    assert server.webadmin.auth.password.get_secret_value() == "webadmin-password"
    assert server.webadmin.auth.client_id == "web"
    assert server.webadmin.auth.client_secret is not None
    assert server.webadmin.auth.client_secret.get_secret_value() == "secret"
    assert settings.oauth2_config is None
    assert settings.uses_oauth2 is False


def test_settings_parse_oauth2_environment_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(SettingsEnv.TIMEBASE_USERNAME, "service-user")
    monkeypatch.setenv(
        SettingsEnv.TIMEBASE_OAUTH2_TOKEN_URL, "https://idp.example/token"
    )
    monkeypatch.setenv(SettingsEnv.TIMEBASE_OAUTH2_CLIENT_ID, "client-id")
    monkeypatch.setenv(SettingsEnv.TIMEBASE_OAUTH2_CLIENT_SECRET, "client-secret")
    monkeypatch.setenv(
        SettingsEnv.TIMEBASE_OAUTH2_SCOPE, "timebase.read   timebase.write"
    )
    monkeypatch.setenv(
        SettingsEnv.TIMEBASE_OAUTH2_TOKEN_PARAMS,
        '{"audience": "timebase-api", "resource": "tb"}',
    )

    settings = MCPSettings()

    assert settings.tb_username == "service-user"
    assert settings.tb_password is None
    assert settings.tb_oauth2_token_url == "https://idp.example/token"
    assert settings.tb_oauth2_client_id == "client-id"
    assert settings.tb_oauth2_client_secret is not None
    assert settings.tb_oauth2_client_secret.get_secret_value() == "client-secret"
    assert settings.tb_oauth2_scope == "timebase.read timebase.write"
    assert settings.tb_oauth2_token_params == {
        "audience": "timebase-api",
        "resource": "tb",
    }
    assert settings.oauth2_config is not None
    assert settings.oauth2_config.token_url == "https://idp.example/token"
    assert settings.oauth2_config.client_id == "client-id"
    assert settings.oauth2_config.client_secret == "client-secret"
    assert settings.oauth2_config.scope == "timebase.read timebase.write"
    assert settings.oauth2_config.token_params == {
        "audience": "timebase-api",
        "resource": "tb",
    }
    assert settings.tb_username == "service-user"
    assert settings.uses_oauth2 is True


def test_settings_default_oauth2_username_to_client_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        SettingsEnv.TIMEBASE_OAUTH2_TOKEN_URL, "https://idp.example/token"
    )
    monkeypatch.setenv(SettingsEnv.TIMEBASE_OAUTH2_CLIENT_ID, "client-id")
    monkeypatch.setenv(SettingsEnv.TIMEBASE_OAUTH2_CLIENT_SECRET, "client-secret")

    settings = MCPSettings()

    assert settings.oauth2_config is not None
    assert settings.tb_username == "client-id"
    assert settings.uses_oauth2 is True


def test_settings_normalize_oauth2_scope_list_input() -> None:
    settings = MCPSettings.model_validate(
        {
            "tb_username": "service-user",
            "tb_oauth2_token_url": "https://idp.example/token",
            "tb_oauth2_client_id": "client-id",
            "tb_oauth2_client_secret": SecretStr("client-secret"),
            "tb_oauth2_scope": ["timebase.read", "timebase.write extra"],
        }
    )

    assert settings.tb_oauth2_scope == "timebase.read timebase.write extra"
    assert settings.oauth2_config is not None
    assert settings.oauth2_config.scope == "timebase.read timebase.write extra"


def test_settings_ignore_empty_environment_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(SettingsEnv.TIMEBASE_URL, "")
    monkeypatch.setenv(SettingsEnv.TIMEBASE_USERNAME, "")
    monkeypatch.setenv(SettingsEnv.TIMEBASE_PASSWORD, "")
    monkeypatch.setenv(SettingsEnv.TIMEBASE_OAUTH2_TOKEN_URL, "")
    monkeypatch.setenv(SettingsEnv.TIMEBASE_OAUTH2_CLIENT_ID, "")
    monkeypatch.setenv(SettingsEnv.TIMEBASE_OAUTH2_CLIENT_SECRET, "")
    monkeypatch.setenv(SettingsEnv.TIMEBASE_OAUTH2_SCOPE, "")
    monkeypatch.setenv(SettingsEnv.TIMEBASE_OAUTH2_TOKEN_PARAMS, "")
    monkeypatch.setenv(SettingsEnv.MCP_TRANSPORT, "")
    monkeypatch.setenv(SettingsEnv.MCP_HOST, "")
    monkeypatch.setenv(SettingsEnv.MCP_PORT, "")
    monkeypatch.setenv(SettingsEnv.MCP_LOG_LEVEL, "")
    monkeypatch.setenv(SettingsEnv.MCP_MAX_CONCURRENT_OPS, "")
    monkeypatch.setenv(SettingsEnv.MCP_OPERATION_TIMEOUT_SECONDS, "")

    settings = MCPSettings()

    assert settings.tb_url == DEFAULT_TIMEBASE_URL
    assert settings.tb_username is None
    assert settings.tb_password is None
    assert settings.tb_oauth2_token_url is None
    assert settings.tb_oauth2_client_id is None
    assert settings.tb_oauth2_client_secret is None
    assert settings.tb_oauth2_scope is None
    assert settings.tb_oauth2_token_params is None
    assert settings.webadmin.url is None
    assert settings.transport == DEFAULT_TRANSPORT
    assert settings.host == DEFAULT_HOST
    assert settings.port == DEFAULT_PORT
    assert settings.log_level == "INFO"
    assert settings.max_concurrent_ops == 0
    assert settings.max_idle_clients == 0
    assert settings.operation_timeout_seconds == 60
    assert settings.oauth2_config is None
    assert settings.uses_oauth2 is False


@pytest.mark.parametrize(
    ("environment_variable", "value"),
    [
        (SettingsEnv.MCP_MAX_CONCURRENT_OPS, "-1"),
        (SettingsEnv.MCP_MAX_IDLE_CLIENTS, "-1"),
        (SettingsEnv.MCP_OPERATION_TIMEOUT_SECONDS, "-5"),
    ],
)
def test_settings_raise_validation_error_for_invalid_guardrail_values(
    monkeypatch: pytest.MonkeyPatch,
    environment_variable: str,
    value: str,
) -> None:
    monkeypatch.setenv(environment_variable, value)

    with pytest.raises(ValidationError):
        MCPSettings()


@pytest.mark.parametrize(
    ("max_idle_clients", "max_concurrent_ops", "expected"),
    [
        (0, 10, 5),
        (0, 1, 1),
        (0, 0, 1),
        (4, 10, 4),
    ],
)
def test_settings_resolve_shared_max_idle_clients(
    max_idle_clients: int,
    max_concurrent_ops: int,
    expected: int,
) -> None:
    settings = MCPSettings(
        max_idle_clients=max_idle_clients,
        max_concurrent_ops=max_concurrent_ops,
    )

    assert settings.resolved_shared_max_idle_clients() == expected


def test_settings_raise_validation_error_for_invalid_port(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(SettingsEnv.MCP_PORT, "not-an-int")

    with pytest.raises(ValidationError):
        MCPSettings()


def test_settings_store_detected_edition() -> None:
    settings = MCPSettings()
    settings.set_detected_edition("community")

    assert settings.detected_edition == "community"


def test_settings_raise_validation_error_for_invalid_log_level(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(SettingsEnv.MCP_LOG_LEVEL, "verbose")

    with pytest.raises(ValidationError):
        MCPSettings()


def test_settings_raise_validation_error_for_partial_auth_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(SettingsEnv.TIMEBASE_USERNAME, "testuser")

    with pytest.raises(ValidationError, match="both be set or both be unset"):
        MCPSettings()


def test_settings_extract_basic_auth_credentials_from_timebase_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        SettingsEnv.TIMEBASE_URL, "dxtick://user:pass@timebase.example:8011"
    )

    settings = MCPSettings()

    assert settings.tb_url == "dxtick://timebase.example:8011"
    assert settings.tb_username == "user"
    assert settings.tb_password is not None
    assert settings.tb_password.get_secret_value() == "pass"


def test_settings_extract_basic_auth_credentials_from_cluster_timebase_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        SettingsEnv.TIMEBASE_URL,
        "dxctick://user:pass@host1:8010|host2:8011|host3:8012",
    )

    settings = MCPSettings()

    assert settings.tb_url == "dxctick://host1:8010|host2:8011|host3:8012"
    assert settings.tb_username == "user"
    assert settings.tb_password is not None
    assert settings.tb_password.get_secret_value() == "pass"


def test_settings_raise_validation_error_for_conflicting_username_between_url_and_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        SettingsEnv.TIMEBASE_URL, "dxtick://user:pass@timebase.example:8011"
    )
    monkeypatch.setenv(SettingsEnv.TIMEBASE_USERNAME, "other-user")
    monkeypatch.setenv(SettingsEnv.TIMEBASE_PASSWORD, "pass")

    with pytest.raises(ValidationError, match="TIMEBASE_USERNAME"):
        MCPSettings()


def test_settings_raise_validation_error_for_conflicting_password_between_url_and_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        SettingsEnv.TIMEBASE_URL, "dxtick://user:pass@timebase.example:8011"
    )
    monkeypatch.setenv(SettingsEnv.TIMEBASE_USERNAME, "user")
    monkeypatch.setenv(SettingsEnv.TIMEBASE_PASSWORD, "different")

    with pytest.raises(ValidationError, match="TIMEBASE_PASSWORD"):
        MCPSettings()


def test_settings_allow_matching_credentials_between_url_and_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        SettingsEnv.TIMEBASE_URL, "dxtick://user:pass@timebase.example:8011"
    )
    monkeypatch.setenv(SettingsEnv.TIMEBASE_USERNAME, "user")
    monkeypatch.setenv(SettingsEnv.TIMEBASE_PASSWORD, "pass")

    settings = MCPSettings()

    assert settings.tb_url == "dxtick://timebase.example:8011"
    assert settings.tb_username == "user"
    assert settings.tb_password is not None
    assert settings.tb_password.get_secret_value() == "pass"


def test_settings_raise_validation_error_for_partial_oauth2_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(SettingsEnv.TIMEBASE_USERNAME, "service-user")
    monkeypatch.setenv(
        SettingsEnv.TIMEBASE_OAUTH2_TOKEN_URL, "https://idp.example/token"
    )

    with pytest.raises(
        ValidationError,
        match="TIMEBASE_OAUTH2_CLIENT_ID, TIMEBASE_OAUTH2_CLIENT_SECRET",
    ):
        MCPSettings()


def test_settings_allow_oauth2_without_username(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        SettingsEnv.TIMEBASE_OAUTH2_TOKEN_URL, "https://idp.example/token"
    )
    monkeypatch.setenv(SettingsEnv.TIMEBASE_OAUTH2_CLIENT_ID, "client-id")
    monkeypatch.setenv(SettingsEnv.TIMEBASE_OAUTH2_CLIENT_SECRET, "client-secret")

    settings = MCPSettings()

    assert settings.tb_username == "client-id"


def test_settings_raise_validation_error_for_password_and_oauth2_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(SettingsEnv.TIMEBASE_USERNAME, "service-user")
    monkeypatch.setenv(SettingsEnv.TIMEBASE_PASSWORD, "secret")
    monkeypatch.setenv(
        SettingsEnv.TIMEBASE_OAUTH2_TOKEN_URL, "https://idp.example/token"
    )
    monkeypatch.setenv(SettingsEnv.TIMEBASE_OAUTH2_CLIENT_ID, "client-id")
    monkeypatch.setenv(SettingsEnv.TIMEBASE_OAUTH2_CLIENT_SECRET, "client-secret")

    with pytest.raises(ValidationError, match="cannot be combined with OAuth2"):
        MCPSettings()


def test_settings_raise_validation_error_for_invalid_oauth2_token_params(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(SettingsEnv.TIMEBASE_USERNAME, "service-user")
    monkeypatch.setenv(
        SettingsEnv.TIMEBASE_OAUTH2_TOKEN_URL, "https://idp.example/token"
    )
    monkeypatch.setenv(SettingsEnv.TIMEBASE_OAUTH2_CLIENT_ID, "client-id")
    monkeypatch.setenv(SettingsEnv.TIMEBASE_OAUTH2_CLIENT_SECRET, "client-secret")
    monkeypatch.setenv(SettingsEnv.TIMEBASE_OAUTH2_TOKEN_PARAMS, '["invalid"]')

    with pytest.raises(ValidationError, match="must be a JSON object"):
        MCPSettings()


def test_settings_raise_validation_error_for_reserved_oauth2_token_params(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        SettingsEnv.TIMEBASE_OAUTH2_TOKEN_URL, "https://idp.example/token"
    )
    monkeypatch.setenv(SettingsEnv.TIMEBASE_OAUTH2_CLIENT_ID, "client-id")
    monkeypatch.setenv(SettingsEnv.TIMEBASE_OAUTH2_CLIENT_SECRET, "client-secret")
    monkeypatch.setenv(
        SettingsEnv.TIMEBASE_OAUTH2_TOKEN_PARAMS, '{"scope": "override"}'
    )

    with pytest.raises(ValidationError, match="cannot override reserved"):
        MCPSettings()


def test_servers_print_emits_quoted_json_string(
    tmp_path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    servers_file = tmp_path / "servers.json"
    servers_file.write_text(
        json.dumps(
            [
                {
                    "name": "enterprise",
                    "description": "Enterprise TimeBase",
                    "url": "dxtick://localhost:8011",
                },
                {"name": "community", "url": "dxtick://localhost:8012"},
            ]
        ),
        encoding="utf-8",
    )

    from timebase_mcp.main import main

    exit_code = main(["servers-print", str(servers_file)])

    captured = capsys.readouterr()
    compact = (
        '[{"name":"enterprise","description":"Enterprise TimeBase",'
        '"url":"dxtick://localhost:8011","auth_mode":"auto"},'
        '{"name":"community","url":"dxtick://localhost:8012","auth_mode":"auto"}]'
    )
    assert exit_code == 0
    assert captured.out == json.dumps(compact) + "\n"
    assert captured.err == ""


def test_servers_json_is_parsed_and_default_resolved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        SettingsEnv.TIMEBASE_SERVERS,
        json.dumps(
            [
                {"name": "prod", "url": "dxtick://prod:8011", "auth_mode": "none"},
                {"name": "dev", "url": "dxtick://u:p@dev:8011"},
            ]
        ),
    )

    settings = MCPSettings()
    servers = settings.resolve_servers()

    assert [server.instance_key for server in servers] == ["prod", "dev"]
    assert [server.name for server in servers] == ["prod", "dev"]
    assert servers[0].auth_mode == "none"
    assert servers[1].auth_mode == "basic"
    assert servers[1].username == "u"
    assert servers[1].password is not None
    assert servers[1].password.get_secret_value() == "p"
    assert settings.resolved_default_instance_key == "prod"


def test_servers_use_sanitized_url_as_key_when_name_is_omitted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        SettingsEnv.TIMEBASE_SERVERS,
        json.dumps([{"url": "dxtick://u:p@prod:8011", "description": "Production"}]),
    )

    settings = MCPSettings()
    server = settings.resolve_servers()[0]

    assert server.instance_key == "dxtick://prod:8011"
    assert server.name is None
    assert server.description == "Production"
    assert server.url == "dxtick://prod:8011"
    assert settings.resolved_default_instance_key == "dxtick://prod:8011"


def test_servers_use_name_as_key_when_specified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        SettingsEnv.TIMEBASE_SERVERS,
        json.dumps(
            [
                {
                    "name": "prod",
                    "description": "Production TimeBase",
                    "url": "dxtick://prod:8011",
                },
                {"url": "dxtick://dev:8011"},
            ]
        ),
    )

    settings = MCPSettings()
    servers = settings.resolve_servers()

    assert [server.instance_key for server in servers] == ["prod", "dxtick://dev:8011"]
    assert servers[0].name == "prod"
    assert servers[1].name is None
    assert servers[0].description == "Production TimeBase"
    assert settings.resolved_default_instance_key == "prod"


def test_servers_reject_duplicate_resolved_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        SettingsEnv.TIMEBASE_SERVERS,
        json.dumps(
            [
                {"url": "dxtick://prod:8011"},
                {"url": "dxtick://prod:8011"},
            ]
        ),
    )

    with pytest.raises(ValidationError, match="instance names must be unique"):
        MCPSettings()


def test_servers_url_only_defaults_to_auto(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        SettingsEnv.TIMEBASE_SERVERS,
        json.dumps([{"name": "prod", "url": "dxtick://prod:8011"}]),
    )

    settings = MCPSettings()

    assert settings.resolve_servers()[0].auth_mode == "auto"


def test_server_explicit_auto_allows_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        SettingsEnv.TIMEBASE_SERVERS,
        json.dumps(
            [
                {
                    "name": "prod",
                    "url": "dxtick://prod:8011",
                    "auth_mode": "auto",
                    "username": "u",
                    "password": "p",
                }
            ]
        ),
    )

    settings = MCPSettings()

    server = settings.resolve_servers()[0]
    assert server.auth_mode == "auto"
    assert server.username == "u"
    assert server.password is not None


def test_server_explicit_auto_allows_oauth2(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        SettingsEnv.TIMEBASE_SERVERS,
        json.dumps(
            [
                {
                    "name": "prod",
                    "url": "dxtick://prod:8011",
                    "auth_mode": "auto",
                    "oauth2_token_url": "https://idp.example/token",
                    "oauth2_client_id": "client-id",
                    "oauth2_client_secret": "client-secret",
                }
            ]
        ),
    )

    settings = MCPSettings()

    server = settings.resolve_servers()[0]
    assert server.auth_mode == "auto"
    assert server.oauth2_token_url == "https://idp.example/token"


def test_server_explicit_auto_allows_interactive_oauth_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        SettingsEnv.TIMEBASE_SERVERS,
        json.dumps(
            [
                {
                    "name": "prod",
                    "url": "dxtick://prod:8011",
                    "auth_mode": "auto",
                    "oauth2_client_id": "interactive-client",
                    "oauth2_scope": "openid profile",
                }
            ]
        ),
    )

    settings = MCPSettings()

    server = settings.resolve_servers()[0]
    assert server.auth_mode == "auto"
    assert server.oauth2_client_id == "interactive-client"
    assert server.oauth2_scope == "openid profile"


def test_server_explicit_auto_rejects_ambiguous_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        SettingsEnv.TIMEBASE_SERVERS,
        json.dumps(
            [
                {
                    "name": "prod",
                    "url": "dxtick://prod:8011",
                    "auth_mode": "auto",
                    "username": "u",
                    "password": "p",
                    "oauth2_token_url": "https://idp.example/token",
                    "oauth2_client_id": "client-id",
                    "oauth2_client_secret": "client-secret",
                }
            ]
        ),
    )

    with pytest.raises(ValidationError, match="cannot resolve both"):
        MCPSettings()


def test_server_none_auth_rejects_username(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        SettingsEnv.TIMEBASE_SERVERS,
        json.dumps(
            [
                {
                    "name": "prod",
                    "url": "dxtick://prod:8011",
                    "auth_mode": "none",
                    "username": "u",
                }
            ]
        ),
    )

    with pytest.raises(ValidationError, match="cannot be combined"):
        MCPSettings()


def test_server_oauth2_rejects_reserved_token_params(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        SettingsEnv.TIMEBASE_SERVERS,
        json.dumps(
            [
                {
                    "name": "prod",
                    "url": "dxtick://prod:8011",
                    "auth_mode": "oauth2_client_credentials",
                    "oauth2_token_url": "https://idp.example/token",
                    "oauth2_client_id": "client-id",
                    "oauth2_client_secret": "client-secret",
                    "oauth2_token_params": {"scope": "override"},
                }
            ]
        ),
    )

    with pytest.raises(ValidationError, match="reserved OAuth2 fields"):
        MCPSettings()


def test_servers_conflict_with_flat_connection_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        SettingsEnv.TIMEBASE_SERVERS,
        json.dumps([{"name": "prod", "url": "dxtick://prod:8011"}]),
    )
    monkeypatch.setenv(SettingsEnv.TIMEBASE_USERNAME, "x")
    monkeypatch.setenv(SettingsEnv.TIMEBASE_PASSWORD, "y")

    with pytest.raises(ValidationError, match="cannot be combined"):
        MCPSettings()


def test_servers_load_from_file_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    servers_file = tmp_path / "servers.json"
    servers_file.write_text(
        json.dumps(
            [
                {"name": "prod", "url": "dxtick://prod:8011"},
                {"name": "dev", "url": "dxtick://dev:8011"},
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv(SettingsEnv.TIMEBASE_SERVERS, str(servers_file))

    settings = MCPSettings()
    servers = settings.resolve_servers()

    assert [server.instance_key for server in servers] == ["prod", "dev"]


def test_servers_load_from_indexed_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(SettingsEnv.TIMEBASE_SERVERS, raising=False)
    monkeypatch.setenv(f"{SettingsEnv.TIMEBASE_SERVERS}_0_NAME", "enterprise")
    monkeypatch.setenv(
        f"{SettingsEnv.TIMEBASE_SERVERS}_0_DESCRIPTION", "Enterprise TimeBase"
    )
    monkeypatch.setenv(
        f"{SettingsEnv.TIMEBASE_SERVERS}_0_URL", "dxtick://localhost:8011"
    )
    monkeypatch.setenv(f"{SettingsEnv.TIMEBASE_SERVERS}_1_NAME", "community")
    monkeypatch.setenv(
        f"{SettingsEnv.TIMEBASE_SERVERS}_1_URL", "dxtick://localhost:8012"
    )

    settings = MCPSettings()
    servers = settings.resolve_servers()

    assert [server.instance_key for server in servers] == ["enterprise", "community"]
    assert servers[0].description == "Enterprise TimeBase"


def test_servers_indexed_env_supports_basic_auth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(SettingsEnv.TIMEBASE_SERVERS, raising=False)
    monkeypatch.setenv(f"{SettingsEnv.TIMEBASE_SERVERS}_0_URL", "dxtick://prod:8011")
    monkeypatch.setenv(f"{SettingsEnv.TIMEBASE_SERVERS}_0_USERNAME", "alice")
    monkeypatch.setenv(f"{SettingsEnv.TIMEBASE_SERVERS}_0_PASSWORD", "secret")

    server = MCPSettings().resolve_servers()[0]

    assert server.auth_mode == "basic"
    assert server.username == "alice"
    assert server.password is not None
    assert server.password.get_secret_value() == "secret"


def test_servers_indexed_env_supports_separate_webadmin_auth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(SettingsEnv.TIMEBASE_SERVERS, raising=False)
    prefix = f"{SettingsEnv.TIMEBASE_SERVERS}_0_"
    monkeypatch.setenv(prefix + "URL", "dxtick://prod:8011")
    monkeypatch.setenv(prefix + "WEBADMIN_URL", "http://webadmin:8099")
    monkeypatch.setenv(prefix + "WEBADMIN_USERNAME", "webadmin-user")
    monkeypatch.setenv(prefix + "WEBADMIN_PASSWORD", "webadmin-password")
    monkeypatch.setenv(prefix + "WEBADMIN_CLIENT_ID", "custom-client")
    monkeypatch.setenv(prefix + "WEBADMIN_CLIENT_SECRET", "custom-secret")

    server = MCPSettings().resolve_servers()[0]

    assert server.username is None
    assert server.webadmin.auth.username == "webadmin-user"
    assert server.webadmin.auth.password is not None
    assert server.webadmin.auth.password.get_secret_value() == "webadmin-password"
    assert server.webadmin.auth.client_id == "custom-client"
    assert server.webadmin.auth.client_secret is not None
    assert server.webadmin.auth.client_secret.get_secret_value() == "custom-secret"


@pytest.mark.parametrize(
    "field",
    [
        "webadmin_username",
        "webadmin_password",
        "webadmin_client_id",
        "webadmin_client_secret",
    ],
)
@pytest.mark.parametrize("style", ["flat", "server", "indexed"])
def test_webadmin_auth_requires_complete_pairs(
    field: str, style: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(
        ValidationError, match="must either both be set or both be unset"
    ):
        if style == "flat":
            MCPSettings.model_validate({"tb_" + field: "configured"})
        elif style == "server":
            MCPSettings.model_validate(
                {"servers": [{"url": "dxtick://localhost:8011", field: "configured"}]}
            )
        else:
            monkeypatch.delenv(SettingsEnv.TIMEBASE_SERVERS, raising=False)
            monkeypatch.setenv("TIMEBASE_SERVERS_0_URL", "dxtick://localhost:8011")
            monkeypatch.setenv("TIMEBASE_SERVERS_0_" + field.upper(), "configured")
            MCPSettings()


def test_servers_indexed_env_stops_at_first_missing_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(SettingsEnv.TIMEBASE_SERVERS, raising=False)
    monkeypatch.setenv(
        f"{SettingsEnv.TIMEBASE_SERVERS}_0_URL", "dxtick://localhost:8011"
    )
    monkeypatch.setenv(
        f"{SettingsEnv.TIMEBASE_SERVERS}_2_URL", "dxtick://localhost:8013"
    )

    servers = MCPSettings().resolve_servers()

    assert len(servers) == 1
    assert servers[0].url == "dxtick://localhost:8011"


def test_servers_scalar_cannot_be_combined_with_indexed_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        SettingsEnv.TIMEBASE_SERVERS,
        json.dumps([{"name": "prod", "url": "dxtick://prod:8011"}]),
    )
    monkeypatch.setenv(
        f"{SettingsEnv.TIMEBASE_SERVERS}_0_URL", "dxtick://localhost:8011"
    )

    with pytest.raises(ValidationError, match="cannot be combined"):
        MCPSettings()


def test_default_server_built_from_flat_settings() -> None:
    settings = MCPSettings()
    servers = settings.resolve_servers()

    assert len(servers) == 1
    assert servers[0].instance_key == "default"
    assert servers[0].auth_mode == "auto"


def test_settings_default_to_read_write_connections() -> None:
    settings = MCPSettings()

    assert settings.tb_read_only is False
    assert settings.resolve_servers()[0].read_only is False


def test_read_only_env_applies_to_flat_server(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(SettingsEnv.TIMEBASE_READ_ONLY, "true")

    settings = MCPSettings()

    assert settings.tb_read_only is True
    assert settings.resolve_servers()[0].read_only is True


def test_read_only_parsed_from_servers_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        SettingsEnv.TIMEBASE_SERVERS,
        json.dumps(
            [
                {"name": "prod", "url": "dxtick://prod:8011", "read_only": True},
                {"name": "dev", "url": "dxtick://dev:8011"},
            ]
        ),
    )

    servers = MCPSettings().resolve_servers()

    assert [server.read_only for server in servers] == [True, None]


def test_read_only_parsed_from_servers_file(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    servers_file = tmp_path / "servers.json"
    servers_file.write_text(
        json.dumps([{"name": "prod", "url": "dxtick://prod:8011", "read_only": True}]),
        encoding="utf-8",
    )
    monkeypatch.setenv(SettingsEnv.TIMEBASE_SERVERS, str(servers_file))

    servers = MCPSettings().resolve_servers()

    assert [server.read_only for server in servers] == [True]


@pytest.mark.parametrize(
    ("raw_value", "expected"),
    [("true", True), ("false", False), (None, None)],
)
def test_read_only_parsed_from_indexed_env(
    monkeypatch: pytest.MonkeyPatch,
    raw_value: str | None,
    expected: bool | None,
) -> None:
    monkeypatch.setenv(f"{SettingsEnv.TIMEBASE_SERVERS}_0_URL", "dxtick://prod:8011")
    monkeypatch.setenv(f"{SettingsEnv.TIMEBASE_SERVERS}_0_NAME", "prod")
    monkeypatch.delenv(f"{SettingsEnv.TIMEBASE_SERVERS}_0_READ_ONLY", raising=False)
    if raw_value is not None:
        monkeypatch.setenv(
            f"{SettingsEnv.TIMEBASE_SERVERS}_0_READ_ONLY",
            raw_value,
        )

    servers = MCPSettings().resolve_servers()

    assert [server.read_only for server in servers] == [expected]


def test_read_only_env_combines_with_servers_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(SettingsEnv.TIMEBASE_READ_ONLY, "true")
    monkeypatch.setenv(
        SettingsEnv.TIMEBASE_SERVERS,
        json.dumps([{"name": "prod", "url": "dxtick://prod:8011"}]),
    )

    settings = MCPSettings()

    assert settings.tb_read_only is True
    assert settings.resolve_servers()[0].read_only is None


def test_runtime_applies_read_only_default_to_instances() -> None:
    settings = MCPSettings.model_validate(
        {
            "tb_read_only": True,
            "servers": [
                {"name": "prod", "url": "dxtick://prod:8011"},
                {"name": "dev", "url": "dxtick://dev:8011", "read_only": False},
            ],
        }
    )

    runtime = build_runtime(settings)

    assert runtime.instances["prod"].config.read_only is True
    assert runtime.instances["dev"].config.read_only is False


def test_runtime_applies_per_instance_read_only_without_default() -> None:
    settings = MCPSettings.model_validate(
        {
            "servers": [
                {"name": "prod", "url": "dxtick://prod:8011", "read_only": True},
                {"name": "dev", "url": "dxtick://dev:8011"},
            ],
        }
    )

    runtime = build_runtime(settings)

    assert runtime.instances["prod"].config.read_only is True
    assert runtime.instances["dev"].config.read_only is False


@pytest.mark.parametrize("suffix", ["?key=value", "#fragment", "?", "#"])
@pytest.mark.parametrize(
    "credentials",
    [
        {},
        {"webadmin_username": "user", "webadmin_password": "fixture"},
        {"webadmin_api_key": "key", "webadmin_api_secret": "fixture"},
    ],
)
def test_webadmin_base_url_rejects_query_and_fragment(suffix, credentials):
    from timebase_mcp.config.servers import ServerConfig

    fields = {
        "webadmin_url": "https://webadmin.example/context" + suffix,
        **credentials,
    }
    with pytest.raises(ValidationError, match="query or fragment"):
        ServerConfig.model_validate({"url": "dxtick://localhost:8011", **fields})
    with pytest.raises(ValidationError, match="query or fragment"):
        MCPSettings.model_validate({"tb_" + k: v for k, v in fields.items()})
    with pytest.raises(ValidationError, match="query or fragment"):
        MCPSettings.model_validate(
            {"servers": [{"url": "dxtick://localhost:8011", **fields}]}
        )


@pytest.mark.parametrize("suffix", ["?x=1", "#fragment"])
def test_indexed_webadmin_url_rejects_query_and_fragment(monkeypatch, suffix):
    monkeypatch.setenv("TIMEBASE_SERVERS_0_URL", "dxtick://localhost:8011")
    monkeypatch.setenv(
        "TIMEBASE_SERVERS_0_WEBADMIN_URL", "https://webadmin.example" + suffix
    )
    with pytest.raises(ValidationError, match="query or fragment"):
        MCPSettings()


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:8099/",
        "https://webadmin.example/context/",
        "https://webadmin.example/context%3Fname/",
    ],
)
def test_webadmin_base_url_preserves_valid_context_path(url):
    settings = MCPSettings(webadmin=WebAdminConfig(url=url))
    assert settings.resolve_servers()[0].webadmin.url == url.rstrip("/")


def test_webadmin_config_is_reused_and_secrets_stay_redacted() -> None:
    webadmin = WebAdminConfig(
        url="http://localhost:8099/",
        auth=WebAdminAuthConfig(
            username="reader", password=SecretStr("composition-password")
        ),
    )
    settings = MCPSettings(webadmin=webadmin)
    assert settings.resolve_servers()[0].webadmin is webadmin
    assert build_runtime(settings).get_instance().config.webadmin is webadmin
    assert webadmin.url == "http://localhost:8099"
    payload = settings.debug_log_payload()
    assert payload["webadmin"] == webadmin.model_dump(mode="json")
    assert "composition-password" not in str(payload)
    with pytest.raises(ValidationError, match="frozen"):
        webadmin.auth.username = "changed"


@pytest.mark.parametrize("init_style", ["nested", "flat", "alias"])
def test_webadmin_source_precedence(tmp_path, monkeypatch, init_style) -> None:
    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir()
    (secrets_dir / "TIMEBASE_WEBADMIN_URL").write_text("http://secret-file:8099")
    (secrets_dir / "TIMEBASE_WEBADMIN_USERNAME").write_text("secret-file-user")
    (secrets_dir / "TIMEBASE_WEBADMIN_PASSWORD").write_text("secret-file-password")
    (secrets_dir / "TIMEBASE_WEBADMIN_CLIENT_ID").write_text("secret-file-client")
    (secrets_dir / "TIMEBASE_WEBADMIN_CLIENT_SECRET").write_text(
        "secret-file-client-secret"
    )
    env_file = tmp_path / "settings.env"
    env_file.write_text(
        "TIMEBASE_WEBADMIN_URL=http://dotenv:8099\n"
        "TIMEBASE_WEBADMIN_USERNAME=dotenv-user\n"
        "TIMEBASE_WEBADMIN_PASSWORD=dotenv-password\n"
    )
    monkeypatch.setenv("TIMEBASE_WEBADMIN_URL", "http://environment:8099")
    monkeypatch.setenv("TIMEBASE_WEBADMIN_USERNAME", "environment-user")
    monkeypatch.setenv("TIMEBASE_WEBADMIN_PASSWORD", "")
    inputs = {
        "nested": {"webadmin": {"auth": {"username": "explicit-user"}}},
        "flat": {"tb_webadmin_username": "explicit-user"},
        "alias": {"TIMEBASE_WEBADMIN_USERNAME": "explicit-user"},
    }
    settings = MCPSettings.model_validate(
        {"_env_file": env_file, "_secrets_dir": secrets_dir, **inputs[init_style]}
    )
    assert settings.webadmin == WebAdminConfig(
        url="http://environment:8099",
        auth=WebAdminAuthConfig(
            username="explicit-user",
            password=SecretStr("dotenv-password"),
            client_id="secret-file-client",
            client_secret=SecretStr("secret-file-client-secret"),
        ),
    )


def test_servers_print_preserves_flat_webadmin_fields(tmp_path, capsys) -> None:
    from timebase_mcp.config.servers import ServerConfig
    from timebase_mcp.main import main

    entry = {
        "url": "dxtick://localhost:8011",
        "webadmin_url": "http://localhost:8099",
        "webadmin_auth_mode": "bearer_file",
        "webadmin_token_file": "/tmp/token",
    }
    path = tmp_path / "servers.json"
    path.write_text(json.dumps([entry]))
    assert main(["servers-print", str(path)]) == 0
    printed = json.loads(json.loads(capsys.readouterr().out))
    assert printed == [{**entry, "auth_mode": "auto"}]
    assert ServerConfig.model_validate(printed[0]) == ServerConfig.model_validate(entry)
