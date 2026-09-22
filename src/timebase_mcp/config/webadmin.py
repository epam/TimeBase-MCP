from typing import Any, Literal
from urllib.parse import urlparse, urlsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    field_validator,
    model_validator,
)
from pydantic.fields import FieldInfo
from pydantic_settings import (
    EnvSettingsSource,
    PydanticBaseSettingsSource,
    SecretsSettingsSource,
)
from typing_extensions import override

from timebase_mcp.errors import ConfigurationError


def trusted_https_url(value: str) -> tuple[str, str, int]:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or parsed.query
        or any(c.isspace() or ord(c) < 32 for c in value)
    ):
        raise ValueError(
            "WebAdmin OAuth issuer and endpoints require trusted HTTPS URLs without credentials, query or fragment."
        )
    return parsed.scheme, parsed.hostname, parsed.port or 443


class WebAdminAuthConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    mode: Literal["password", "interactive", "client_credentials", "bearer_file"] = (
        "password"
    )
    issuer_url: str | None = None
    scope: str | None = None
    redirect_uri: str | None = None
    token_url: str | None = None
    token_file: str | None = None
    private_key_file: str | None = None
    session_login_root: str | None = None
    api_key: str | None = None
    api_secret: SecretStr | None = None
    username: str | None = None
    password: SecretStr | None = None
    client_id: str | None = None
    client_secret: SecretStr | None = None

    @model_validator(mode="after")
    def validate_credentials(self) -> "WebAdminAuthConfig":
        if (self.username is None) != (self.password is None):
            raise ValueError(
                "WebAdmin username and password must either both be set or both be unset."
            )
        if self.mode == "password" and (self.client_id is None) != (
            self.client_secret is None
        ):
            raise ValueError(
                "WebAdmin client ID and client secret must either both be set or both be unset."
            )
        if (
            self.mode != "password"
            and self.client_secret is not None
            and not self.client_secret.get_secret_value()
        ):
            raise ValueError("WebAdmin client secret must not be empty.")

        self._validate_oauth()

        if self.private_key_file is not None and (
            not self.private_key_file.strip() or self.api_secret is not None
        ):
            raise ValueError(
                "WebAdmin session private key cannot be empty or combined with an API secret."
            )
        if self.session_login_root is not None:
            root = self.session_login_root
            if (
                self.private_key_file is None
                or any(c.isspace() or ord(c) < 32 for c in root)
                or not root.startswith("/")
                or root.startswith("//")
                or any(c in root for c in ("?", "#", ":", "\\", "%"))
                or any(x in {".", "..", ""} for x in root[1:].split("/"))
            ):
                raise ValueError(
                    "WebAdmin session login root must be an absolute local path without traversal, query or fragment."
                )
        if (self.api_key is None) != (
            self.api_secret is None and self.private_key_file is None
        ):
            raise ValueError(
                "WebAdmin API key requires exactly one API secret or session private-key file."
            )
        if self.api_key is not None:
            if not self.api_key.strip() or (
                self.api_secret is not None and not self.api_secret.get_secret_value()
            ):
                raise ValueError("WebAdmin API credentials must not be empty.")
            if self.username is not None or self.client_id is not None:
                raise ValueError(
                    "WebAdmin API keys cannot be combined with WebAdmin OAuth credentials."
                )
        return self

    def _validate_oauth(self) -> None:
        if self.mode == "password":
            if any(
                x is not None
                for x in (
                    self.issuer_url,
                    self.scope,
                    self.redirect_uri,
                    self.token_url,
                    self.token_file,
                )
            ):
                raise ValueError(
                    "Explicit WebAdmin OAuth settings require an explicit auth mode."
                )
            return
        if self.username is not None or self.api_key is not None:
            raise ValueError(
                "WebAdmin OAuth modes cannot be combined with password or API-key credentials."
            )
        if self.mode == "interactive":
            if (
                not self.issuer_url
                or not self.scope
                or not self.scope.strip()
                or not self.client_id
                or not self.client_id.strip()
                or not self.redirect_uri
            ):
                raise ValueError(
                    "WebAdmin interactive auth requires issuer URL, scope, client ID and redirect URI."
                )
            trusted_https_url(self.issuer_url)
            from timebase_mcp.auth.interactive import _parse_redirect_uri

            try:
                _parse_redirect_uri(self.redirect_uri)
            except ConfigurationError as exc:
                raise ValueError(str(exc)) from exc
            if (
                self.client_secret is not None
                or self.token_url is not None
                or self.token_file is not None
            ):
                raise ValueError(
                    "WebAdmin interactive auth uses PKCE without a secret, token URL or token file."
                )
        elif self.mode == "client_credentials":
            if (
                not self.token_url
                or not self.client_id
                or not self.client_id.strip()
                or self.client_secret is None
                or not self.scope
                or not self.scope.strip()
            ):
                raise ValueError(
                    "WebAdmin client_credentials requires token URL, client ID, client secret and scope."
                )
            trusted_https_url(self.token_url)
            if any(
                x is not None
                for x in (self.issuer_url, self.redirect_uri, self.token_file)
            ):
                raise ValueError(
                    "WebAdmin client_credentials cannot include interactive or token-file settings."
                )
        elif self.mode == "bearer_file":
            if not self.token_file or not self.token_file.strip():
                raise ValueError("WebAdmin bearer_file requires a token file.")
            if (
                any(
                    x is not None
                    for x in (
                        self.issuer_url,
                        self.scope,
                        self.redirect_uri,
                        self.token_url,
                        self.client_id,
                    )
                )
                or self.client_secret is not None
            ):
                raise ValueError(
                    "WebAdmin bearer_file cannot include OAuth acquisition settings."
                )


class WebAdminConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    url: str | None = None
    auth: WebAdminAuthConfig = Field(default_factory=WebAdminAuthConfig)

    @field_validator("url")
    @classmethod
    def normalize_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parsed = urlparse(value)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValueError("webadmin_url must be an HTTP(S) URL.")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("webadmin_url must not contain credentials.")
        if "?" in value or "#" in value:
            raise ValueError("WebAdmin URL must not contain query or fragment.")
        return value.rstrip("/")

    @model_validator(mode="after")
    def validate_destination(self) -> "WebAdminConfig":
        if self.auth.mode != "password":
            if self.url is None:
                raise ValueError("WebAdmin OAuth mode requires a WebAdmin URL.")
            target = urlparse(self.url)
            if target.scheme != "https" and target.hostname not in {
                "localhost",
                "127.0.0.1",
                "::1",
            }:
                raise ValueError(
                    "WebAdmin bearer credentials require HTTPS except on loopback."
                )
        return self


# Flat names are accepted only at the configuration input boundary.
WEBADMIN_FIELD_NAMES = (
    "url",
    "auth_mode",
    "issuer_url",
    "scope",
    "redirect_uri",
    "token_url",
    "token_file",
    "private_key_file",
    "session_login_root",
    "api_key",
    "api_secret",
    "username",
    "password",
    "client_id",
    "client_secret",
)
WEBADMIN_ENV_VARS = tuple(
    "TIMEBASE_WEBADMIN_" + name.upper() for name in WEBADMIN_FIELD_NAMES
)


def nest_webadmin_fields(
    value: dict[str, Any], *, prefix: str = "webadmin_"
) -> dict[str, Any]:
    flat = {
        name: value[prefix + name]
        for name in WEBADMIN_FIELD_NAMES
        if prefix + name in value
    }
    if not flat:
        return value
    if "webadmin" in value:
        raise ValueError("Cannot combine nested and flat WebAdmin settings.")
    remaining = value.copy()
    for name in flat:
        remaining.pop(prefix + name)
    webadmin: dict[str, object] = {}
    if "url" in flat:
        webadmin["url"] = flat.pop("url")
    if "auth_mode" in flat:
        flat["mode"] = flat.pop("auth_mode")
    webadmin["auth"] = flat
    remaining["webadmin"] = webadmin
    return remaining


class WebAdminSettingsSource(PydanticBaseSettingsSource):
    """Translate flat inputs before Pydantic merges sources by precedence."""

    def __init__(self, source: PydanticBaseSettingsSource) -> None:
        super().__init__(source.settings_cls)
        self.source = source

    @override
    def get_field_value(
        self, field: FieldInfo, field_name: str
    ) -> tuple[Any, str, bool]:
        return self.source.get_field_value(field, field_name)

    @override
    def __call__(self) -> dict[str, Any]:
        values = self.source()
        if (
            isinstance(self.source, SecretsSettingsSource)
            and self.source.secrets_dir is None
        ):
            return values
        if isinstance(self.source, (EnvSettingsSource, SecretsSettingsSource)):
            for name, env_name in zip(
                WEBADMIN_FIELD_NAMES, WEBADMIN_ENV_VARS, strict=True
            ):
                value, _, _ = self.source.get_field_value(
                    FieldInfo(annotation=str, validation_alias=env_name),
                    "tb_webadmin_" + name,
                )
                if value is not None:
                    values["tb_webadmin_" + name] = value
                values.pop(env_name, None)
                values.pop(env_name.lower(), None)
        else:
            for name, env_name in zip(
                WEBADMIN_FIELD_NAMES, WEBADMIN_ENV_VARS, strict=True
            ):
                if env_name in values:
                    values["tb_webadmin_" + name] = values.pop(env_name)
        return nest_webadmin_fields(values, prefix="tb_webadmin_")
