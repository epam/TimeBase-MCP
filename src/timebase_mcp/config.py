import json
import os
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import unquote, urlparse

from pydantic import (
    BaseModel,
    Field,
    PrivateAttr,
    SecretStr,
    field_validator,
    model_validator,
)
from pydantic.fields import FieldInfo
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from timebase_mcp.auth.oauth2 import (
    OAUTH2_RESERVED_PARAMS,
    OAuth2ClientCredentialsConfig,
)
from timebase_mcp.constants import (
    DEFAULT_HOST,
    DEFAULT_INSTANCE_KEY,
    DEFAULT_PORT,
    DEFAULT_TIMEBASE_URL,
    DEFAULT_TRANSPORT,
    LOOPBACK_HOSTS,
)

Transport = Literal["stdio", "streamable-http"]
Edition = Literal["community", "enterprise"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
InboundAuthMode = Literal["none", "jwt", "api_key"]
OutboundAuthMode = Literal[
    "auto",
    "none",
    "basic",  # username + password
    "oauth2_client_credentials",  # service account OAuth2 client-credentials
    "forward_identity",  # forward the authenticated caller's bearer token to TimeBase
    "interactive",  # MCP runs an interactive OAuth login to TimeBase's IdP
]

_HTTP_TRANSPORTS: frozenset[Transport] = frozenset({"streamable-http"})


class SettingsEnv:
    TIMEBASE_URL = "TIMEBASE_URL"
    TIMEBASE_USERNAME = "TIMEBASE_USERNAME"
    TIMEBASE_PASSWORD = "TIMEBASE_PASSWORD"
    TIMEBASE_OAUTH2_TOKEN_URL = "TIMEBASE_OAUTH2_TOKEN_URL"
    TIMEBASE_OAUTH2_CLIENT_ID = "TIMEBASE_OAUTH2_CLIENT_ID"
    TIMEBASE_OAUTH2_CLIENT_SECRET = "TIMEBASE_OAUTH2_CLIENT_SECRET"
    TIMEBASE_OAUTH2_SCOPE = "TIMEBASE_OAUTH2_SCOPE"
    TIMEBASE_OAUTH2_TOKEN_PARAMS = "TIMEBASE_OAUTH2_TOKEN_PARAMS"
    TIMEBASE_AUTH_MODE = "TIMEBASE_AUTH_MODE"
    TIMEBASE_HTTP_URL = "TIMEBASE_HTTP_URL"
    TIMEBASE_SERVERS = "TIMEBASE_SERVERS"
    MCP_TRANSPORT = "MCP_TRANSPORT"
    MCP_HOST = "MCP_HOST"
    MCP_PORT = "MCP_PORT"
    MCP_LOG_LEVEL = "MCP_LOG_LEVEL"
    MCP_MAX_CONCURRENT_OPS = "MCP_MAX_CONCURRENT_OPS"
    MCP_OPERATION_TIMEOUT_SECONDS = "MCP_OPERATION_TIMEOUT_SECONDS"
    MCP_AUTH_ISSUER_URL = "MCP_AUTH_ISSUER_URL"
    MCP_AUTH_JWKS_URL = "MCP_AUTH_JWKS_URL"
    MCP_AUTH_AUDIENCE = "MCP_AUTH_AUDIENCE"
    MCP_AUTH_REQUIRED_SCOPES = "MCP_AUTH_REQUIRED_SCOPES"
    MCP_AUTH_PUBLIC_URL = "MCP_AUTH_PUBLIC_URL"
    MCP_AUTH_API_KEYS_FILE = "MCP_AUTH_API_KEYS_FILE"


_OAUTH2_CONFIG_FIELDS = (
    "tb_oauth2_token_url",
    "tb_oauth2_client_id",
    "tb_oauth2_client_secret",
    "tb_oauth2_scope",
    "tb_oauth2_token_params",
)
_OAUTH2_REQUIRED_FIELDS = _OAUTH2_CONFIG_FIELDS[:3]
_OAUTH2_SERVICE_EVIDENCE_FIELDS = (
    "tb_oauth2_token_url",
    "tb_oauth2_client_secret",
    "tb_oauth2_token_params",
)
_OAUTH2_INTERACTIVE_FORBIDDEN_FIELDS = (
    "tb_oauth2_token_url",
    "tb_oauth2_client_secret",
    "tb_oauth2_token_params",
)
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

    if payload.get("servers"):
        payload["servers"] = _REDACTED_SECRET_VALUE

    return _redact_log_payload(payload)


def _normalize_required_scopes(value: object) -> object:
    """Accept a space/comma-delimited string or list and return a list[str]|None."""
    if value in (None, ""):
        return None

    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            parsed = value
        else:
            if isinstance(parsed, list):
                value = parsed
            else:
                value = str(parsed)

    if isinstance(value, str):
        tokens = [token for token in value.replace(",", " ").split() if token]
        return tokens or None

    if isinstance(value, list | tuple):
        tokens = []
        for item in value:
            if not isinstance(item, str):
                raise ValueError("Scope values must be strings.")
            tokens.extend(token for token in item.replace(",", " ").split() if token)
        return tokens or None

    raise ValueError("Scope values must be a string or a list of strings.")


_INDEXED_SERVER_ENV_FIELDS: tuple[tuple[str, str], ...] = (
    ("NAME", "name"),
    ("DESCRIPTION", "description"),
    ("USERNAME", "username"),
    ("PASSWORD", "password"),
)


def _indexed_servers_present() -> bool:
    return os.environ.get(f"{SettingsEnv.TIMEBASE_SERVERS}_0_URL") is not None


def _servers_from_indexed_env() -> list[dict[str, object]] | None:
    servers: list[dict[str, object]] = []
    index = 0
    while True:
        url_key = f"{SettingsEnv.TIMEBASE_SERVERS}_{index}_URL"
        url = os.environ.get(url_key)
        if not url:
            break

        entry: dict[str, object] = {"url": url}
        for suffix, field_name in _INDEXED_SERVER_ENV_FIELDS:
            value = os.environ.get(f"{SettingsEnv.TIMEBASE_SERVERS}_{index}_{suffix}")
            if value:
                entry[field_name] = value
        servers.append(entry)
        index += 1

    return servers or None


def _parse_servers_json_payload(
    payload: object, *, source: str
) -> list[dict[str, object]]:
    if not isinstance(payload, list):
        raise ValueError(f"{source} must contain a JSON array of server objects.")
    return payload


def _load_servers_scalar(value: str) -> list[dict[str, object]]:
    stripped = value.strip()
    if not stripped:
        raise ValueError("TIMEBASE_SERVERS must not be empty.")

    if stripped.startswith("["):
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise ValueError(
                "TIMEBASE_SERVERS must be valid JSON (an array of server objects)."
            ) from exc
        return _parse_servers_json_payload(payload, source="TIMEBASE_SERVERS")

    path = Path(stripped)
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(
            f"Cannot read TIMEBASE_SERVERS file {stripped!r}: {exc}"
        ) from exc

    try:
        payload = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"TIMEBASE_SERVERS file {stripped!r} must contain valid JSON."
        ) from exc

    return _parse_servers_json_payload(
        payload,
        source=f"TIMEBASE_SERVERS file {stripped!r}",
    )


def load_servers_from_path(path: str | Path) -> list[dict[str, object]]:
    """Load server definitions from a JSON file path."""
    return _load_servers_scalar(str(path))


def _load_servers(*, scalar: str | None = None) -> list[dict[str, object]] | None:
    env_scalar = (
        scalar if scalar is not None else os.environ.get(SettingsEnv.TIMEBASE_SERVERS)
    )
    if env_scalar not in (None, ""):
        if _indexed_servers_present():
            raise ValueError(
                "TIMEBASE_SERVERS cannot be combined with TIMEBASE_SERVERS_{n}_URL "
                "indexed variables."
            )
        return _load_servers_scalar(env_scalar)

    return _servers_from_indexed_env()


def _infer_outbound_auth_mode(
    *,
    username: str | None,
    password: SecretStr | None,
    oauth2_service_evidence_present: bool,
) -> OutboundAuthMode:
    if oauth2_service_evidence_present:
        return "oauth2_client_credentials"
    if username is not None or password is not None:
        return "basic"
    return "auto"


def _oauth2_fields_present(source: object, fields: tuple[str, ...]) -> bool:
    return any(getattr(source, field_name) is not None for field_name in fields)


def _is_loopback_host(host: str) -> bool:
    return host in LOOPBACK_HOSTS


def _is_remote_http_bind(*, transport: Transport, host: str) -> bool:
    return transport in _HTTP_TRANSPORTS and not _is_loopback_host(host)


def _is_loopback_or_local_url(value: str) -> bool:
    parsed = urlparse(value)
    host = parsed.hostname
    return host is not None and _is_loopback_host(host)


def _is_https_url(value: str) -> bool:
    return urlparse(value).scheme.casefold() == "https"


class ServerConfig(BaseModel):
    """Connection settings for a single named TimeBase server.

    Parsed from ``TIMEBASE_SERVERS`` (JSON string or file) or indexed env vars.
    """

    name: str | None = Field(
        default=None,
        min_length=1,
        description=(
            "Optional friendly server name. When set, this is also the instance "
            "key used by MCP tools."
        ),
    )
    description: str | None = Field(
        default=None,
        description="Optional server description exposed to MCP clients.",
    )
    url: str = Field(min_length=1)
    auth_mode: OutboundAuthMode | None = None
    username: str | None = None
    password: SecretStr | None = None
    oauth2_token_url: str | None = None
    oauth2_client_id: str | None = None
    oauth2_client_secret: SecretStr | None = None
    oauth2_scope: str | None = None
    oauth2_token_params: dict[str, str] | None = None
    http_base_url: str | None = Field(
        default=None,
        description="Base URL of the TimeBase HTTP API (e.g. for OAuth discovery )."
        "Defaults are derived from the TB URL when omitted.",
    )

    @field_validator("oauth2_scope", mode="before")
    @classmethod
    def _normalize_scope(cls, value: object) -> object:
        return _normalize_oauth2_scope(value)

    @field_validator("oauth2_token_params", mode="before")
    @classmethod
    def _normalize_token_params(cls, value: object) -> object:
        return _normalize_oauth2_token_params(value)

    @property
    def instance_key(self) -> str:
        return self.name or self.url

    @property
    def oauth2_present(self) -> bool:
        return _oauth2_fields_present(
            self,
            (
                "oauth2_token_url",
                "oauth2_client_id",
                "oauth2_client_secret",
                "oauth2_scope",
                "oauth2_token_params",
            ),
        )

    @property
    def oauth2_service_evidence_present(self) -> bool:
        return _oauth2_fields_present(
            self,
            (
                "oauth2_token_url",
                "oauth2_client_secret",
                "oauth2_token_params",
            ),
        )

    @model_validator(mode="after")
    def _resolve(self) -> "ServerConfig":
        sanitized_url, extracted_username, extracted_password = (
            _extract_timebase_url_credentials(self.url)
        )
        self.url = sanitized_url

        if extracted_username is not None and self.username is None:
            self.username = extracted_username
        if extracted_password is not None and self.password is None:
            self.password = SecretStr(extracted_password)

        oauth2_present = self.oauth2_present
        oauth2_service_evidence = self.oauth2_service_evidence_present
        mode = self.auth_mode or _infer_outbound_auth_mode(
            username=self.username,
            password=self.password,
            oauth2_service_evidence_present=oauth2_service_evidence,
        )

        if mode == "basic":
            if self.username is None or self.password is None:
                raise ValueError(
                    f"Server '{self.instance_key}': basic auth requires username and password."
                )
        elif mode == "oauth2_client_credentials":
            if self.password is not None:
                raise ValueError(
                    f"Server '{self.instance_key}': oauth2_client_credentials cannot be combined "
                    "with password."
                )

            missing = [
                name
                for name, present in (
                    ("oauth2_token_url", self.oauth2_token_url is not None),
                    ("oauth2_client_id", self.oauth2_client_id is not None),
                    ("oauth2_client_secret", self.oauth2_client_secret is not None),
                )
                if not present
            ]
            if missing:
                raise ValueError(
                    f"Server '{self.instance_key}': oauth2_client_credentials requires "
                    + ", ".join(missing)
                    + "."
                )

            self._validate_reserved_oauth2_token_params()

            if self.username is None:
                self.username = self.oauth2_client_id
        elif mode in ("none", "forward_identity"):
            if self.username is not None or self.password is not None or oauth2_present:
                raise ValueError(
                    f"Server '{self.instance_key}': auth_mode '{mode}' cannot be combined "
                    "with username, password, or oauth2 client-credentials settings."
                )
        elif mode == "interactive":
            forbidden = [
                name
                for name, present in (
                    ("username", self.username is not None),
                    ("password", self.password is not None),
                    ("oauth2_token_url", self.oauth2_token_url is not None),
                    ("oauth2_client_secret", self.oauth2_client_secret is not None),
                    ("oauth2_token_params", self.oauth2_token_params is not None),
                )
                if present
            ]
            if forbidden:
                raise ValueError(
                    f"Server '{self.instance_key}': auth_mode 'interactive' cannot be "
                    "combined with " + ", ".join(forbidden) + "."
                )
        elif mode == "auto":
            if (self.username is None) != (
                self.password is None
            ) and not oauth2_service_evidence:
                raise ValueError(
                    f"Server '{self.instance_key}': auth_mode 'auto' requires username and "
                    "password together when resolving basic auth."
                )
            if self.password is not None and self.username is None:
                raise ValueError(
                    f"Server '{self.instance_key}': auth_mode 'auto' cannot resolve a "
                    "password without username."
                )
            if self.password is not None and oauth2_service_evidence:
                raise ValueError(
                    f"Server '{self.instance_key}': auth_mode 'auto' cannot resolve both "
                    "password and oauth2 client-credentials settings."
                )
            if oauth2_service_evidence:
                missing = [
                    name
                    for name, present in (
                        ("oauth2_token_url", self.oauth2_token_url is not None),
                        ("oauth2_client_id", self.oauth2_client_id is not None),
                        (
                            "oauth2_client_secret",
                            self.oauth2_client_secret is not None,
                        ),
                    )
                    if not present
                ]
                if missing:
                    raise ValueError(
                        f"Server '{self.instance_key}': auth_mode 'auto' with OAuth2 "
                        "settings requires " + ", ".join(missing) + "."
                    )
                self._validate_reserved_oauth2_token_params()

        self.auth_mode = mode
        return self

    def _validate_reserved_oauth2_token_params(self) -> None:
        extra_token_params = self.oauth2_token_params or {}
        conflicting_params = sorted(
            name for name in extra_token_params if name in OAUTH2_RESERVED_PARAMS
        )
        if conflicting_params:
            raise ValueError(
                f"Server '{self.instance_key}': oauth2_token_params cannot override "
                "reserved OAuth2 fields: " + ", ".join(conflicting_params) + "."
            )

    def has_service_oauth2_evidence(self) -> bool:
        return self.oauth2_service_evidence_present


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
    operation_timeout_seconds: int = Field(
        default=0,
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
        description="TimeBase REST base URL used for OAuth discovery (/tb/oauthinfo).",
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
            return _load_servers(scalar=value)
        if value in (None, ""):
            return _load_servers()
        return value

    @field_validator("log_level", mode="before")
    @classmethod
    def normalize_log_level(cls, value: object) -> object:
        return _normalize_log_level(value)

    @field_validator("auth_required_scopes", mode="before")
    @classmethod
    def normalize_required_scopes(cls, value: object) -> object:
        return _normalize_required_scopes(value)

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
        if self.servers is not None:
            return self._validate_servers_list()

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

        oauth2_config_present = _oauth2_fields_present(self, _OAUTH2_CONFIG_FIELDS)
        oauth2_service_evidence_present = _oauth2_fields_present(
            self,
            _OAUTH2_SERVICE_EVIDENCE_FIELDS,
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
                _field_env_name(field_name, type(self).model_fields[field_name])
                for field_name in (
                    "tb_password",
                    *_OAUTH2_INTERACTIVE_FORBIDDEN_FIELDS,
                )
                if getattr(self, field_name) is not None
            ]
            if self.tb_username is not None:
                forbidden_fields.insert(
                    0,
                    _field_env_name(
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
                    _field_env_name(field_name, type(self).model_fields[field_name])
                    for field_name in _OAUTH2_REQUIRED_FIELDS
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
            or any(getattr(self, name) is not None for name in _OAUTH2_CONFIG_FIELDS)
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
        if jwt_inbound_auth_enabled and _is_remote_http_bind(
            transport=self.transport,
            host=self.host,
        ):
            if self.auth_public_url is None:
                raise ValueError(
                    "Inbound JWT auth on a non-loopback HTTP bind requires "
                    "MCP_AUTH_PUBLIC_URL set to the public HTTPS MCP endpoint."
                )
            if not _is_https_url(
                self.auth_public_url
            ) and not _is_loopback_or_local_url(self.auth_public_url):
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
        return _is_remote_http_bind(transport=self.transport, host=self.host)

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

        oauth2_config_present = _oauth2_fields_present(
            self,
            _OAUTH2_SERVICE_EVIDENCE_FIELDS,
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
