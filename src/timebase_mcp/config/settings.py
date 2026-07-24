import os
from typing import Annotated

from pydantic import Field, PrivateAttr, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from timebase_mcp.auth.oauth2 import (
    OAUTH2_RESERVED_PARAMS,
    OAuth2ClientCredentialsConfig,
)
from timebase_mcp.config.diagnostics import (
    field_env_name,
    redact_log_payload,
    sanitize_env_log_payload,
)
from timebase_mcp.config.env import SettingsEnv
from timebase_mcp.config.normalizers import (
    normalize_log_level,
    normalize_oauth2_scope,
    normalize_oauth2_token_params,
    normalize_required_scopes,
)
from timebase_mcp.config.oauth import (
    OAUTH2_CONFIG_FIELDS,
    OAUTH2_INTERACTIVE_FORBIDDEN_FIELDS,
    OAUTH2_REQUIRED_FIELDS,
    OAUTH2_SERVICE_EVIDENCE_FIELDS,
    oauth2_fields_present,
)
from timebase_mcp.config.servers import ServerConfig, load_servers
from timebase_mcp.config.types import (
    _HTTP_TRANSPORTS,
    Edition,
    InboundAuthMode,
    LogLevel,
    OutboundAuthMode,
    Transport,
)
from timebase_mcp.config.urls import (
    extract_timebase_url_credentials,
    is_https_url,
    is_loopback_or_local_url,
    is_remote_http_bind,
)
from timebase_mcp.constants import (
    DEFAULT_HOST,
    DEFAULT_INSTANCE_KEY,
    DEFAULT_PORT,
    DEFAULT_TIMEBASE_URL,
    DEFAULT_TRANSPORT,
)


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
        description="TimeBase connection URL",
    )
    tb_username: str | None = Field(
        default=None,
        validation_alias=SettingsEnv.TIMEBASE_USERNAME,
        description="Username for basic auth",
    )
    tb_password: SecretStr | None = Field(
        default=None,
        validation_alias=SettingsEnv.TIMEBASE_PASSWORD,
        description="Password for basic auth",
    )
    tb_oauth2_token_url: str | None = Field(
        default=None,
        validation_alias=SettingsEnv.TIMEBASE_OAUTH2_TOKEN_URL,
        description="OAuth2 token endpoint",
    )
    tb_oauth2_client_id: str | None = Field(
        default=None,
        validation_alias=SettingsEnv.TIMEBASE_OAUTH2_CLIENT_ID,
        description="OAuth2 client ID",
    )
    tb_oauth2_client_secret: SecretStr | None = Field(
        default=None,
        validation_alias=SettingsEnv.TIMEBASE_OAUTH2_CLIENT_SECRET,
        description="OAuth2 client secret",
    )
    tb_oauth2_scope: str | None = Field(
        default=None,
        validation_alias=SettingsEnv.TIMEBASE_OAUTH2_SCOPE,
        description="OAuth2 scopes",
    )
    tb_oauth2_token_params: Annotated[dict[str, str] | None, NoDecode] = Field(
        default=None,
        validation_alias=SettingsEnv.TIMEBASE_OAUTH2_TOKEN_PARAMS,
        description="Extra OAuth2 token request parameters",
    )
    transport: Transport = Field(
        default=DEFAULT_TRANSPORT,
        validation_alias=SettingsEnv.MCP_TRANSPORT,
        description="Transport for MCP server to use",
    )
    host: str = Field(
        default=DEFAULT_HOST,
        validation_alias=SettingsEnv.MCP_HOST,
        description="Host for MCP server to listen on",
    )
    port: int = Field(
        default=DEFAULT_PORT,
        ge=1,
        le=65535,
        validation_alias=SettingsEnv.MCP_PORT,
        description="Port for MCP server to listen on",
    )
    log_level: LogLevel = Field(
        default="INFO",
        validation_alias=SettingsEnv.MCP_LOG_LEVEL,
        description="Logging level",
    )
    max_concurrent_ops: int = Field(
        default=0,
        ge=0,
        validation_alias=SettingsEnv.MCP_MAX_CONCURRENT_OPS,
        description=(
            "Maximum concurrent TimeBase operations. 0 disables admission control."
        ),
    )
    max_idle_clients: int = Field(
        default=0,
        ge=0,
        validation_alias=SettingsEnv.MCP_MAX_IDLE_CLIENTS,
        description=(
            "Maximum idle TimeBase connections kept per shared pool. "
            "0 selects max(1, MCP_MAX_CONCURRENT_OPS / 2)."
        ),
    )
    operation_timeout_seconds: int = Field(
        default=60,
        ge=0,
        validation_alias=SettingsEnv.MCP_OPERATION_TIMEOUT_SECONDS,
        description=(
            "Per-operation timeout in seconds. 0 disables deadline enforcement."
        ),
    )
    tb_auth_mode: OutboundAuthMode | None = Field(
        default=None,
        validation_alias=SettingsEnv.TIMEBASE_AUTH_MODE,
        description=(
            "Outbound TimeBase auth mode for the default (flat) server. When unset "
            "it is inferred from the supplied credentials."
        ),
    )
    tb_http_url: str | None = Field(
        default=None,
        validation_alias=SettingsEnv.TIMEBASE_HTTP_URL,
        description="TimeBase HTTP API base URL.",
    )
    servers: Annotated[list[ServerConfig] | None, NoDecode] = Field(
        default=None,
        validation_alias=SettingsEnv.TIMEBASE_SERVERS,
        description=(
            "Optional list of TimeBase servers as a JSON string, file path, or "
            "indexed TIMEBASE_SERVERS_{n}_* env vars. Replaces flat TIMEBASE_* "
            "connection settings."
        ),
    )
    auth_issuer_url: str | None = Field(
        default=None,
        validation_alias=SettingsEnv.MCP_AUTH_ISSUER_URL,
        description="OAuth issuer URL override (otherwise discovered from TimeBase).",
    )
    auth_jwks_url: str | None = Field(
        default=None,
        validation_alias=SettingsEnv.MCP_AUTH_JWKS_URL,
        description="JWKS URL override (otherwise discovered from the issuer).",
    )
    auth_audience: str | None = Field(
        default=None,
        validation_alias=SettingsEnv.MCP_AUTH_AUDIENCE,
        description="Expected JWT audience. When unset audience is not verified.",
    )
    auth_required_scopes: Annotated[list[str] | None, NoDecode] = Field(
        default=None,
        validation_alias=SettingsEnv.MCP_AUTH_REQUIRED_SCOPES,
        description="Scopes required on inbound tokens (space/comma delimited).",
    )
    auth_public_url: str | None = Field(
        default=None,
        validation_alias=SettingsEnv.MCP_AUTH_PUBLIC_URL,
        description=(
            "Public URL of this MCP Resource Server, used in OAuth protected "
            "resource metadata and authentication challenges. Not the authorization "
            "server / IdP URL. Defaults to http://host:port."
        ),
    )
    auth_api_keys_file: str | None = Field(
        default=None,
        validation_alias=SettingsEnv.MCP_AUTH_API_KEYS_FILE,
        description=(
            "Path to a JSON store of hashed API keys accepted as inbound bearer "
            "tokens (managed out-of-band via `timebase-mcp keys`). Selects API-key "
            "auth instead of IdP/JWT; re-read live so rotation needs no restart."
        ),
    )

    @field_validator("servers", mode="before")
    @classmethod
    def normalize_servers(cls, value: object) -> object:
        if isinstance(value, list):
            return value
        if isinstance(value, str):
            return load_servers(scalar=value)
        if value in (None, ""):
            return load_servers()
        return value

    @field_validator("log_level", mode="before")
    @classmethod
    def normalize_log_level(cls, value: object) -> object:
        return normalize_log_level(value)

    @field_validator("auth_required_scopes", mode="before")
    @classmethod
    def normalize_required_scopes(cls, value: object) -> object:
        return normalize_required_scopes(value)

    @field_validator("tb_oauth2_scope", mode="before")
    @classmethod
    def normalize_oauth2_scope(cls, value: object) -> object:
        return normalize_oauth2_scope(value)

    @field_validator("tb_oauth2_token_params", mode="before")
    @classmethod
    def normalize_oauth2_token_params(
        cls,
        value: object,
    ) -> object:
        return normalize_oauth2_token_params(value)

    @model_validator(mode="after")
    def validate_auth_pair(self) -> "MCPSettings":
        if self.servers is not None:
            return self._validate_servers_list()

        sanitized_tb_url, extracted_username, extracted_password = (
            extract_timebase_url_credentials(self.tb_url)
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

        oauth2_config_present = oauth2_fields_present(self, OAUTH2_CONFIG_FIELDS)
        oauth2_service_evidence_present = oauth2_fields_present(
            self,
            OAUTH2_SERVICE_EVIDENCE_FIELDS,
        )

        if self.tb_auth_mode in ("none", "forward_identity"):
            if (
                self.tb_username is not None
                or self.tb_password is not None
                or oauth2_config_present
            ):
                raise ValueError(
                    f"TIMEBASE_AUTH_MODE '{self.tb_auth_mode}' cannot be combined "
                    "with TIMEBASE_USERNAME, TIMEBASE_PASSWORD, or OAuth2 client "
                    "credentials settings."
                )
            return self

        if self.tb_auth_mode == "interactive":
            forbidden_fields = [
                field_env_name(field_name, type(self).model_fields[field_name])
                for field_name in (
                    "tb_password",
                    *OAUTH2_INTERACTIVE_FORBIDDEN_FIELDS,
                )
                if getattr(self, field_name) is not None
            ]
            if self.tb_username is not None:
                forbidden_fields.insert(
                    0,
                    field_env_name(
                        "tb_username", type(self).model_fields["tb_username"]
                    ),
                )
            if forbidden_fields:
                raise ValueError(
                    "TIMEBASE_AUTH_MODE 'interactive' cannot be combined with "
                    + ", ".join(forbidden_fields)
                    + ". Use TIMEBASE_OAUTH2_CLIENT_ID and TIMEBASE_OAUTH2_SCOPE "
                    "only as interactive login overrides."
                )
            return self

        if self.tb_auth_mode == "auto":
            if (self.tb_username is None) != (
                self.tb_password is None
            ) and not oauth2_service_evidence_present:
                raise ValueError(
                    "TIMEBASE_AUTH_MODE 'auto' requires TIMEBASE_USERNAME and "
                    "TIMEBASE_PASSWORD together when resolving basic auth."
                )
            if self.tb_password is not None and self.tb_username is None:
                raise ValueError(
                    "TIMEBASE_AUTH_MODE 'auto' cannot resolve TIMEBASE_PASSWORD "
                    "without TIMEBASE_USERNAME."
                )
            if self.tb_password is not None and oauth2_service_evidence_present:
                raise ValueError(
                    "TIMEBASE_AUTH_MODE 'auto' cannot resolve both "
                    "TIMEBASE_PASSWORD and OAuth2 client credentials settings."
                )
            if oauth2_service_evidence_present:
                missing_fields = [
                    field_env_name(field_name, type(self).model_fields[field_name])
                    for field_name in OAUTH2_REQUIRED_FIELDS
                    if getattr(self, field_name) is None
                ]
                if missing_fields:
                    raise ValueError(
                        "TIMEBASE_AUTH_MODE 'auto' with OAuth2 settings requires "
                        + ", ".join(missing_fields)
                        + "."
                    )
                self._validate_reserved_flat_oauth2_token_params()
            return self

        if self.tb_password is not None and oauth2_service_evidence_present:
            raise ValueError(
                "TIMEBASE_PASSWORD cannot be combined with OAuth2 client credentials settings."
            )

        if oauth2_service_evidence_present:
            missing_fields = [
                field_env_name(field_name, type(self).model_fields[field_name])
                for field_name in OAUTH2_REQUIRED_FIELDS
                if getattr(self, field_name) is None
            ]
            if missing_fields:
                raise ValueError(
                    "OAuth2 client credentials authentication requires "
                    + ", ".join(missing_fields)
                    + "."
                )

            self._validate_reserved_flat_oauth2_token_params()

            if self.tb_username is None:
                self.tb_username = self.tb_oauth2_client_id

            return self

        if self.tb_auth_mode == "oauth2_client_credentials":
            raise ValueError(
                "TIMEBASE_AUTH_MODE 'oauth2_client_credentials' requires "
                "TIMEBASE_OAUTH2_TOKEN_URL, TIMEBASE_OAUTH2_CLIENT_ID, and "
                "TIMEBASE_OAUTH2_CLIENT_SECRET."
            )

        if self.tb_auth_mode == "basic" and (
            self.tb_username is None or self.tb_password is None
        ):
            raise ValueError(
                "TIMEBASE_AUTH_MODE 'basic' requires TIMEBASE_USERNAME and "
                "TIMEBASE_PASSWORD."
            )

        if (self.tb_username is None) != (self.tb_password is None):
            raise ValueError(
                "TimeBase username and password must either both be set or both be unset."
            )

        return self

    def _validate_reserved_flat_oauth2_token_params(self) -> None:
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

    def _validate_servers_list(self) -> "MCPSettings":
        assert self.servers is not None
        flat_connection_configured = (
            self.tb_username is not None
            or self.tb_password is not None
            or self.tb_auth_mode is not None
            or self.tb_http_url is not None
            or any(getattr(self, name) is not None for name in OAUTH2_CONFIG_FIELDS)
        )
        if flat_connection_configured:
            raise ValueError(
                "TIMEBASE_SERVERS cannot be combined with the flat TIMEBASE_* "
                "connection settings (TIMEBASE_USERNAME/PASSWORD/OAUTH2_*/AUTH_MODE)."
            )

        if not self.servers:
            raise ValueError("TIMEBASE_SERVERS must contain at least one server.")

        instance_names = [server.instance_key for server in self.servers]
        if len(set(instance_names)) != len(instance_names):
            raise ValueError("TIMEBASE_SERVERS instance names must be unique.")

        return self

    @model_validator(mode="after")
    def validate_inbound_consistency(self) -> "MCPSettings":
        jwt_inbound_auth_enabled = self.inbound_auth_mode == "jwt"
        if jwt_inbound_auth_enabled and is_remote_http_bind(
            transport=self.transport,
            host=self.host,
        ):
            if self.auth_public_url is None:
                raise ValueError(
                    "Inbound JWT auth on a non-loopback HTTP bind requires "
                    "MCP_AUTH_PUBLIC_URL set to the public HTTPS MCP endpoint."
                )
            if not is_https_url(self.auth_public_url) and not is_loopback_or_local_url(
                self.auth_public_url
            ):
                raise ValueError(
                    "MCP_AUTH_PUBLIC_URL must use HTTPS for non-loopback JWT "
                    "inbound auth."
                )

        servers = self.resolve_servers()
        forwards_identity = any(
            server.auth_mode == "forward_identity" for server in servers
        )
        if forwards_identity:
            if not self.inbound_auth_enabled:
                raise ValueError("auth_mode 'forward_identity' requires inbound auth.")
            if self.transport not in _HTTP_TRANSPORTS:
                raise ValueError(
                    "auth_mode 'forward_identity' requires an HTTP transport "
                    "(MCP_TRANSPORT=streamable-http)."
                )
            if self.auth_api_keys_file:
                raise ValueError(
                    "auth_mode 'forward_identity' cannot be combined with an API key "
                    "store (MCP_AUTH_API_KEYS_FILE); API-key callers have no bearer "
                    "token to forward to TimeBase."
                )
        uses_interactive = any(server.auth_mode == "interactive" for server in servers)
        if uses_interactive and self.is_http_transport:
            raise ValueError(
                "auth_mode 'interactive' is only supported for stdio transport. "
                "Use forward_identity, oauth2_client_credentials, basic, or none "
                "for HTTP deployments."
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
    def is_http_transport(self) -> bool:
        return self.transport in _HTTP_TRANSPORTS

    @property
    def is_remote_http_bind(self) -> bool:
        return is_remote_http_bind(transport=self.transport, host=self.host)

    @property
    def inbound_auth_enabled(self) -> bool:
        if not self.is_http_transport:
            return False
        return self.auth_audience is not None or self.auth_api_keys_file is not None

    @property
    def inbound_auth_mode(self) -> InboundAuthMode:
        if not self.inbound_auth_enabled or not self.is_http_transport:
            return "none"
        if self.auth_api_keys_file:
            return "api_key"
        return "jwt"

    def _default_auth_mode(self) -> OutboundAuthMode | None:
        if self.tb_auth_mode is not None:
            return self.tb_auth_mode

        oauth2_config_present = oauth2_fields_present(
            self,
            OAUTH2_SERVICE_EVIDENCE_FIELDS,
        )
        if (
            self.tb_username is None
            and self.tb_password is None
            and not oauth2_config_present
        ):
            return "auto"

        return None

    def _default_server_config(self) -> ServerConfig:
        return ServerConfig(
            name=DEFAULT_INSTANCE_KEY,
            url=self.tb_url,
            auth_mode=self._default_auth_mode(),
            username=self.tb_username,
            password=self.tb_password,
            oauth2_token_url=self.tb_oauth2_token_url,
            oauth2_client_id=self.tb_oauth2_client_id,
            oauth2_client_secret=self.tb_oauth2_client_secret,
            oauth2_scope=self.tb_oauth2_scope,
            oauth2_token_params=self.tb_oauth2_token_params,
            http_base_url=self.tb_http_url,
        )

    def resolve_servers(self) -> list[ServerConfig]:
        """Return the configured TimeBase servers.

        Uses ``TIMEBASE_SERVERS`` when provided, otherwise builds a single
        ``default`` server from the flat ``TIMEBASE_*`` settings.
        """
        if self.servers:
            return list(self.servers)
        return [self._default_server_config()]

    @property
    def resolved_default_instance_key(self) -> str:
        return self.resolve_servers()[0].instance_key

    @property
    def detected_edition(self) -> Edition | None:
        return self._detected_edition

    def set_detected_edition(self, edition: Edition) -> None:
        self._detected_edition = edition

    @property
    def resolved_interactive_redirect_uri(self) -> str | None:
        if self.transport != "stdio":
            return None

        from timebase_mcp.auth.interactive import resolve_interactive_redirect_uri

        return resolve_interactive_redirect_uri(host=self.host, port=self.port)

    def resolved_shared_max_idle_clients(self) -> int:
        if self.max_idle_clients > 0:
            return self.max_idle_clients
        if self.max_concurrent_ops > 0:
            return max(1, self.max_concurrent_ops // 2)
        return 1

    @classmethod
    def debug_log_payload_from_env(cls) -> dict[str, object]:
        payload: dict[str, object] = {
            field_name: raw_value
            for field_name, field_info in cls.model_fields.items()
            if (raw_value := os.getenv(field_env_name(field_name, field_info)))
            not in (None, "")
        }

        return sanitize_env_log_payload(payload)

    def debug_log_payload(self) -> dict[str, object]:
        return redact_log_payload(self.model_dump(mode="json"))


SETTINGS_ENV_VARS = tuple(
    field_env_name(field_name, field_info)
    for field_name, field_info in MCPSettings.model_fields.items()
)
