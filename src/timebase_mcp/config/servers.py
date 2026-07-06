import json
import os
from pathlib import Path

from pydantic import BaseModel, Field, SecretStr, field_validator, model_validator

from timebase_mcp.auth.oauth2 import OAUTH2_RESERVED_PARAMS
from timebase_mcp.config.env import SettingsEnv
from timebase_mcp.config.normalizers import (
    normalize_oauth2_scope,
    normalize_oauth2_token_params,
)
from timebase_mcp.config.oauth import (
    infer_outbound_auth_mode,
    oauth2_fields_present,
)
from timebase_mcp.config.types import OutboundAuthMode
from timebase_mcp.config.urls import extract_timebase_url_credentials

INDEXED_SERVER_ENV_FIELDS: tuple[tuple[str, str], ...] = (
    ("NAME", "name"),
    ("DESCRIPTION", "description"),
    ("USERNAME", "username"),
    ("PASSWORD", "password"),
)


def indexed_servers_present() -> bool:
    return os.environ.get(f"{SettingsEnv.TIMEBASE_SERVERS}_0_URL") is not None


def servers_from_indexed_env() -> list[dict[str, object]] | None:
    servers: list[dict[str, object]] = []
    index = 0
    while True:
        url_key = f"{SettingsEnv.TIMEBASE_SERVERS}_{index}_URL"
        url = os.environ.get(url_key)
        if not url:
            break

        entry: dict[str, object] = {"url": url}
        for suffix, field_name in INDEXED_SERVER_ENV_FIELDS:
            value = os.environ.get(f"{SettingsEnv.TIMEBASE_SERVERS}_{index}_{suffix}")
            if value:
                entry[field_name] = value
        servers.append(entry)
        index += 1

    return servers or None


def parse_servers_json_payload(
    payload: object, *, source: str
) -> list[dict[str, object]]:
    if not isinstance(payload, list):
        raise ValueError(f"{source} must contain a JSON array of server objects.")
    return payload


def load_servers_scalar(value: str) -> list[dict[str, object]]:
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
        return parse_servers_json_payload(payload, source="TIMEBASE_SERVERS")

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

    return parse_servers_json_payload(
        payload,
        source=f"TIMEBASE_SERVERS file {stripped!r}",
    )


def load_servers_from_path(path: str | Path) -> list[dict[str, object]]:
    """Load server definitions from a JSON file path."""
    return load_servers_scalar(str(path))


def load_servers(*, scalar: str | None = None) -> list[dict[str, object]] | None:
    env_scalar = (
        scalar if scalar is not None else os.environ.get(SettingsEnv.TIMEBASE_SERVERS)
    )
    if env_scalar not in (None, ""):
        if indexed_servers_present():
            raise ValueError(
                "TIMEBASE_SERVERS cannot be combined with TIMEBASE_SERVERS_{n}_URL "
                "indexed variables."
            )
        return load_servers_scalar(env_scalar)

    return servers_from_indexed_env()


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
        description="Base URL of the TimeBase HTTP API. Defaults are derived "
        "from the TB URL when omitted.",
    )

    @field_validator("oauth2_scope", mode="before")
    @classmethod
    def _normalize_scope(cls, value: object) -> object:
        return normalize_oauth2_scope(value)

    @field_validator("oauth2_token_params", mode="before")
    @classmethod
    def _normalize_token_params(cls, value: object) -> object:
        return normalize_oauth2_token_params(value)

    @property
    def instance_key(self) -> str:
        return self.name or self.url

    @property
    def oauth2_present(self) -> bool:
        return oauth2_fields_present(
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
        return oauth2_fields_present(
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
            extract_timebase_url_credentials(self.url)
        )
        self.url = sanitized_url

        if extracted_username is not None and self.username is None:
            self.username = extracted_username
        if extracted_password is not None and self.password is None:
            self.password = SecretStr(extracted_password)

        oauth2_present = self.oauth2_present
        oauth2_service_evidence = self.oauth2_service_evidence_present
        mode = self.auth_mode or infer_outbound_auth_mode(
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
