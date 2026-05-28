import json
import os
from typing import Annotated, Literal
from urllib.parse import unquote

from pydantic import Field, PrivateAttr, SecretStr, field_validator, model_validator
from pydantic.fields import FieldInfo
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from timebase_mcp.constants import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    DEFAULT_TIMEBASE_URL,
    DEFAULT_TRANSPORT,
)
from timebase_mcp.oauth2 import OAUTH2_RESERVED_PARAMS, OAuth2ClientCredentialsConfig

Transport = Literal["stdio", "sse", "streamable-http"]
Edition = Literal["community", "enterprise"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class SettingsEnv:
    TIMEBASE_URL = "TIMEBASE_URL"
    TIMEBASE_USERNAME = "TIMEBASE_USERNAME"
    TIMEBASE_PASSWORD = "TIMEBASE_PASSWORD"
    TIMEBASE_OAUTH2_TOKEN_URL = "TIMEBASE_OAUTH2_TOKEN_URL"
    TIMEBASE_OAUTH2_CLIENT_ID = "TIMEBASE_OAUTH2_CLIENT_ID"
    TIMEBASE_OAUTH2_CLIENT_SECRET = "TIMEBASE_OAUTH2_CLIENT_SECRET"
    TIMEBASE_OAUTH2_SCOPE = "TIMEBASE_OAUTH2_SCOPE"
    TIMEBASE_OAUTH2_TOKEN_PARAMS = "TIMEBASE_OAUTH2_TOKEN_PARAMS"
    MCP_TRANSPORT = "MCP_TRANSPORT"
    MCP_HOST = "MCP_HOST"
    MCP_PORT = "MCP_PORT"
    MCP_LOG_LEVEL = "MCP_LOG_LEVEL"


_OAUTH2_CONFIG_FIELDS = (
    "tb_oauth2_token_url",
    "tb_oauth2_client_id",
    "tb_oauth2_client_secret",
    "tb_oauth2_scope",
    "tb_oauth2_token_params",
)
_OAUTH2_REQUIRED_FIELDS = _OAUTH2_CONFIG_FIELDS[:3]
_SECRET_FIELDS = frozenset({"tb_password", "tb_oauth2_client_secret"})

_REDACTED_SECRET_VALUE = "**********"


def _split_authority_and_suffix(value: str) -> tuple[str, str]:
    delimiter_positions = [value.find(delimiter) for delimiter in ("/", "?", "#")]
    valid_positions = [position for position in delimiter_positions if position >= 0]
    if not valid_positions:
        return value, ""

    authority_end = min(valid_positions)
    return value[:authority_end], value[authority_end:]


def _extract_timebase_url_credentials(
    tb_url: str,
) -> tuple[str, str | None, str | None]:
    prefix = ""
    remainder = tb_url
    if "://" in tb_url:
        scheme, remainder = tb_url.split("://", 1)
        prefix = f"{scheme}://"

    authority, suffix = _split_authority_and_suffix(remainder)
    if "@" not in authority:
        return tb_url, None, None

    userinfo, host_part = authority.rsplit("@", 1)
    if not userinfo or not host_part:
        return tb_url, None, None

    username_part, separator, password_part = userinfo.partition(":")
    username = unquote(username_part)
    password = unquote(password_part) if separator else None
    sanitized_url = f"{prefix}{host_part}{suffix}"
    return sanitized_url, username, password


def _field_env_name(field_name: str, field_info: FieldInfo) -> str:
    validation_alias = field_info.validation_alias
    if validation_alias is None:
        return field_name

    if isinstance(validation_alias, str):
        return validation_alias

    raise TypeError(
        f"MCPSettings field {field_name!r} must use a string validation_alias."
    )


def _normalize_log_level(value: object) -> object:
    if isinstance(value, str):
        return value.upper()
    return value


def _normalize_oauth2_scope(value: object) -> object:
    if value in (None, ""):
        return None

    if isinstance(value, str):
        normalized_scope = " ".join(value.split())
        return normalized_scope or None

    if isinstance(value, list | tuple):
        normalized_scopes: list[str] = []
        for item in value:
            if not isinstance(item, str):
                raise ValueError(
                    "TIMEBASE_OAUTH2_SCOPE must be a string or a list of strings."
                )
            normalized_scopes.extend(part for part in item.split() if part)

        return " ".join(normalized_scopes) or None

    raise ValueError("TIMEBASE_OAUTH2_SCOPE must be a string or a list of strings.")


def _normalize_oauth2_token_params(value: object) -> object:
    if value in (None, ""):
        return None

    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError(
                "TIMEBASE_OAUTH2_TOKEN_PARAMS must be valid JSON."
            ) from exc

    if not isinstance(value, dict):
        raise ValueError(
            "TIMEBASE_OAUTH2_TOKEN_PARAMS must be a JSON object with string keys and values."
        )

    normalized_params: dict[str, str] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not isinstance(item, str):
            raise ValueError(
                "TIMEBASE_OAUTH2_TOKEN_PARAMS must be a JSON object with string keys and values."
            )
        normalized_params[key] = item

    return normalized_params


def _redact_log_payload(payload: dict[str, object]) -> dict[str, object]:
    for secret_field in _SECRET_FIELDS:
        if payload.get(secret_field) is not None:
            payload[secret_field] = _REDACTED_SECRET_VALUE

    return payload


def _sanitize_env_log_payload(payload: dict[str, object]) -> dict[str, object]:
    tb_url = payload.get("tb_url")
    if isinstance(tb_url, str):
        sanitized_tb_url, extracted_username, extracted_password = (
            _extract_timebase_url_credentials(tb_url)
        )
        payload["tb_url"] = sanitized_tb_url

        if payload.get("tb_username") is None and extracted_username is not None:
            payload["tb_username"] = extracted_username

        if payload.get("tb_password") is None and extracted_password is not None:
            payload["tb_password"] = _REDACTED_SECRET_VALUE

    return _redact_log_payload(payload)


class MCPSettings(BaseSettings):
    """Runtime settings for the TimeBase MCP server"""

    _detected_edition: Edition | None = PrivateAttr(default=None)

    model_config = SettingsConfigDict(
        env_prefix="",
        env_ignore_empty=True,
        extra="ignore",
        populate_by_name=True,
    )

    tb_url: str = Field(
        default=DEFAULT_TIMEBASE_URL,
        min_length=1,
        validation_alias=SettingsEnv.TIMEBASE_URL,
    )
    tb_username: str | None = Field(
        default=None,
        validation_alias=SettingsEnv.TIMEBASE_USERNAME,
    )
    tb_password: SecretStr | None = Field(
        default=None,
        validation_alias=SettingsEnv.TIMEBASE_PASSWORD,
    )
    tb_oauth2_token_url: str | None = Field(
        default=None,
        validation_alias=SettingsEnv.TIMEBASE_OAUTH2_TOKEN_URL,
    )
    tb_oauth2_client_id: str | None = Field(
        default=None,
        validation_alias=SettingsEnv.TIMEBASE_OAUTH2_CLIENT_ID,
    )
    tb_oauth2_client_secret: SecretStr | None = Field(
        default=None,
        validation_alias=SettingsEnv.TIMEBASE_OAUTH2_CLIENT_SECRET,
    )
    tb_oauth2_scope: str | None = Field(
        default=None,
        validation_alias=SettingsEnv.TIMEBASE_OAUTH2_SCOPE,
    )
    tb_oauth2_token_params: Annotated[dict[str, str] | None, NoDecode] = Field(
        default=None,
        validation_alias=SettingsEnv.TIMEBASE_OAUTH2_TOKEN_PARAMS,
    )
    transport: Transport = Field(
        default=DEFAULT_TRANSPORT,
        validation_alias=SettingsEnv.MCP_TRANSPORT,
    )
    host: str = Field(default=DEFAULT_HOST, validation_alias=SettingsEnv.MCP_HOST)
    port: int = Field(
        default=DEFAULT_PORT,
        ge=1,
        le=65535,
        validation_alias=SettingsEnv.MCP_PORT,
    )
    log_level: LogLevel = Field(
        default="INFO",
        validation_alias=SettingsEnv.MCP_LOG_LEVEL,
    )

    @field_validator("log_level", mode="before")
    @classmethod
    def normalize_log_level(cls, value: object) -> object:
        return _normalize_log_level(value)

    @field_validator("tb_oauth2_scope", mode="before")
    @classmethod
    def normalize_oauth2_scope(cls, value: object) -> object:
        return _normalize_oauth2_scope(value)

    @field_validator("tb_oauth2_token_params", mode="before")
    @classmethod
    def normalize_oauth2_token_params(
        cls,
        value: object,
    ) -> object:
        return _normalize_oauth2_token_params(value)

    @model_validator(mode="after")
    def validate_auth_pair(self) -> "MCPSettings":
        sanitized_tb_url, extracted_username, extracted_password = (
            _extract_timebase_url_credentials(self.tb_url)
        )
        self.tb_url = sanitized_tb_url

        if extracted_username is not None:
            if self.tb_username is not None and self.tb_username != extracted_username:
                raise ValueError(
                    "TIMEBASE_USERNAME conflicts with username embedded in TIMEBASE_URL."
                )
            self.tb_username = extracted_username

        if extracted_password is not None:
            if self.tb_password is not None:
                existing_password = self.tb_password.get_secret_value()
                if existing_password != extracted_password:
                    raise ValueError(
                        "TIMEBASE_PASSWORD conflicts with password embedded in TIMEBASE_URL."
                    )
            else:
                self.tb_password = SecretStr(extracted_password)

        oauth2_config_present = any(
            getattr(self, field_name) is not None
            for field_name in _OAUTH2_CONFIG_FIELDS
        )

        if self.tb_password is not None and oauth2_config_present:
            raise ValueError(
                "TIMEBASE_PASSWORD cannot be combined with OAuth2 client credentials settings."
            )

        if oauth2_config_present:
            missing_fields = [
                _field_env_name(field_name, type(self).model_fields[field_name])
                for field_name in _OAUTH2_REQUIRED_FIELDS
                if getattr(self, field_name) is None
            ]
            if missing_fields:
                raise ValueError(
                    "OAuth2 client credentials authentication requires "
                    + ", ".join(missing_fields)
                    + "."
                )

            extra_token_params = self.tb_oauth2_token_params or {}
            conflicting_params = sorted(
                name for name in extra_token_params if name in OAUTH2_RESERVED_PARAMS
            )
            if conflicting_params:
                raise ValueError(
                    "TIMEBASE_OAUTH2_TOKEN_PARAMS cannot override reserved OAuth2 fields: "
                    + ", ".join(conflicting_params)
                    + "."
                )

            if self.tb_username is None:
                self.tb_username = self.tb_oauth2_client_id

            return self

        if (self.tb_username is None) != (self.tb_password is None):
            raise ValueError(
                "TimeBase username and password must either both be set or both be unset."
            )

        return self

    def _required_oauth2_values(self) -> tuple[str, str, SecretStr] | None:
        token_url = self.tb_oauth2_token_url
        client_id = self.tb_oauth2_client_id
        client_secret = self.tb_oauth2_client_secret

        if token_url is None or client_id is None or client_secret is None:
            return None

        return token_url, client_id, client_secret

    @property
    def uses_oauth2(self) -> bool:
        return self._required_oauth2_values() is not None

    @property
    def oauth2_config(self) -> OAuth2ClientCredentialsConfig | None:
        required_values = self._required_oauth2_values()
        if required_values is None:
            return None

        token_url, client_id, client_secret = required_values

        return OAuth2ClientCredentialsConfig(
            token_url=token_url,
            client_id=client_id,
            client_secret=client_secret.get_secret_value(),
            scope=self.tb_oauth2_scope,
            token_params=self.tb_oauth2_token_params,
        )

    @property
    def detected_edition(self) -> Edition | None:
        return self._detected_edition

    def set_detected_edition(self, edition: Edition) -> None:
        self._detected_edition = edition

    @classmethod
    def debug_log_payload_from_env(cls) -> dict[str, object]:
        payload: dict[str, object] = {
            field_name: raw_value
            for field_name, field_info in cls.model_fields.items()
            if (raw_value := os.getenv(_field_env_name(field_name, field_info)))
            not in (None, "")
        }

        return _sanitize_env_log_payload(payload)

    def debug_log_payload(self) -> dict[str, object]:
        return _redact_log_payload(self.model_dump(mode="json"))


SETTINGS_ENV_VARS = tuple(
    _field_env_name(field_name, field_info)
    for field_name, field_info in MCPSettings.model_fields.items()
)
