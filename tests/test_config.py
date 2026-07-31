import json

import pytest
from pydantic import SecretStr, ValidationError

from timebase_mcp.config.env import SettingsEnv
from timebase_mcp.config.settings import MCPSettings
from timebase_mcp.runtime.state import build_runtime
from timebase_mcp.constants import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    DEFAULT_TIMEBASE_URL,
    DEFAULT_TRANSPORT,
)


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
    assert settings.tb_username is None
    assert settings.uses_oauth2 is False
    assert settings.detected_edition is None
    assert settings.transport == DEFAULT_TRANSPORT
    assert settings.host == DEFAULT_HOST
    assert settings.port == DEFAULT_PORT
    assert settings.log_level == "INFO"
    assert settings.max_concurrent_ops == 0
    assert settings.max_idle_clients == 0
    assert settings.operation_timeout_seconds == 60


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
