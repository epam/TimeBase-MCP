import json

import pytest
from pydantic import SecretStr
from pydantic import ValidationError

from timebase_mcp.config import MCPSettings, SettingsEnv
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
    assert settings.operation_timeout_seconds == 0


def test_settings_parse_environment_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(SettingsEnv.TIMEBASE_URL, "dxtick://timebase.example:8011")
    monkeypatch.setenv(SettingsEnv.TIMEBASE_USERNAME, "alice")
    monkeypatch.setenv(SettingsEnv.TIMEBASE_PASSWORD, "secret")
    monkeypatch.setenv(SettingsEnv.MCP_TRANSPORT, "streamable-http")
    monkeypatch.setenv(SettingsEnv.MCP_HOST, "0.0.0.0")
    monkeypatch.setenv(SettingsEnv.MCP_PORT, "8080")
    monkeypatch.setenv(SettingsEnv.MCP_LOG_LEVEL, "debug")
    monkeypatch.setenv(SettingsEnv.MCP_MAX_CONCURRENT_OPS, "4")
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
    assert settings.operation_timeout_seconds == 0
    assert settings.oauth2_config is None
    assert settings.uses_oauth2 is False


@pytest.mark.parametrize(
    ("environment_variable", "value"),
    [
        (SettingsEnv.MCP_MAX_CONCURRENT_OPS, "-1"),
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
