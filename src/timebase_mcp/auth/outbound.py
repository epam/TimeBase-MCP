from __future__ import annotations

import base64
import logging
import os
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Literal, NoReturn
from urllib.parse import urlparse

from timebase_mcp.auth.principal import current_principal
from timebase_mcp.auth.token_verifier import decode_claims_unverified
from timebase_mcp.config.env import DXAPI_SSL_TERMINATION_ENV
from timebase_mcp.config.types import OutboundAuthMode
from timebase_mcp.errors import (
    ConfigurationError,
    TimeBaseConnectionError,
    TimeBaseOperationStateError,
)

if TYPE_CHECKING:
    from timebase_mcp.runtime.instance import (
        TimeBaseInstanceConfig,
        TimeBaseInstanceRuntime,
    )

logger = logging.getLogger(__name__)

TimeBaseCredentialsKind = Literal["anonymous", "basic", "bearer"]


@dataclass(frozen=True, slots=True)
class TimeBaseCredentials:
    kind: TimeBaseCredentialsKind
    username: str | None = None
    password: str | None = None
    token: str | None = None


def resolve_auto_auth_config(
    instance: TimeBaseInstanceRuntime,
    config: TimeBaseInstanceConfig,
) -> TimeBaseInstanceConfig:
    if config.auth_mode != "auto":
        return config

    discovered_http_base_url, discovery_error = _discover_timebase_oauth_base_url(
        instance,
        config,
    )
    resolved_mode = _select_auto_auth_mode(
        instance,
        config,
        timebase_advertises_oauth=discovered_http_base_url is not None,
    )
    resolved_config = replace(
        config,
        auth_mode=resolved_mode,
        http_base_url=discovered_http_base_url or config.http_base_url,
        auto_auth_error=discovery_error,
    )

    if instance.config is config:
        instance.config = resolved_config

    logger.info(
        "Resolved TimeBase auth_mode=auto for %s to %s.",
        config.tb_url,
        resolved_mode,
    )
    return resolved_config


def resolve_timebase_credentials(
    instance: TimeBaseInstanceRuntime,
    *,
    error_type: Literal["connection", "operation"] = "connection",
) -> TimeBaseCredentials:
    if instance.config.access_token is not None:
        logger.debug(
            "Connecting to TimeBase at %s with forwarded caller identity.",
            instance.config.tb_url,
        )
        return TimeBaseCredentials(
            kind="bearer",
            username=username_for_token(
                instance.config.access_token,
                instance.config.access_token_username or instance.config.tb_username,
            ),
            token=instance.config.access_token,
        )

    if instance.config.auth_mode == "forward_identity":
        principal = current_principal()
        if principal is None or not principal.token:
            message = "TimeBase forwards caller identity but the request is not authenticated."
            if instance is not None:
                message = (
                    f"TimeBase server '{instance.key}' forwards caller identity but "
                    "the request is not authenticated."
                )
            raise TimeBaseOperationStateError(message)

        return TimeBaseCredentials(
            kind="bearer",
            username=username_for_token(
                principal.token,
                principal.username or instance.config.tb_username,
            ),
            token=principal.token,
        )

    if instance.config.auth_mode == "interactive":
        try:
            logger.debug(
                "Connecting to TimeBase at %s with interactive login.",
                instance.config.tb_url,
            )
            token = instance.get_interactive_provider().get_access_token()
        except (ValueError, PermissionError, ConnectionError) as exc:
            _raise_credential_error(
                f"Interactive login to TimeBase at '{instance.config.tb_url}' failed: {exc}",
                error_type,
                cause=exc,
            )
        return TimeBaseCredentials(
            kind="bearer",
            username=username_for_token(token, instance.config.tb_username),
            token=token,
        )

    oauth2_config = instance.config.oauth2_config
    if (
        instance.config.auth_mode == "oauth2_client_credentials"
        or oauth2_config is not None
    ):
        if oauth2_config is None:
            _raise_credential_error(
                "OAuth2 client-credentials auth is not fully configured.",
                error_type,
            )
        try:
            logger.debug(
                "Obtaining OAuth2 client-credentials token for TimeBase at %s.",
                instance.config.tb_url,
            )
            access_token = instance.get_oauth2_provider(
                oauth2_config
            ).get_access_token()
        except (ValueError, PermissionError, ConnectionError) as exc:
            _raise_credential_error(
                "Failed to obtain OAuth2 credentials for TimeBase at "
                f"'{instance.config.tb_url}': {exc}",
                error_type,
                cause=exc,
            )

        return TimeBaseCredentials(
            kind="bearer",
            username=instance.config.tb_username or oauth2_config.client_id,
            token=access_token,
        )

    password = None
    if instance.config.tb_password is not None:
        password = instance.config.tb_password.get_secret_value()

    if instance.config.tb_username is None and password is None:
        return TimeBaseCredentials(kind="anonymous")

    username = instance.config.tb_username
    assert username is not None
    assert password is not None
    return TimeBaseCredentials(kind="basic", username=username, password=password)


def build_http_auth_headers(
    instance: TimeBaseInstanceRuntime,
) -> dict[str, str]:
    credentials = resolve_timebase_credentials(
        instance,
        error_type="operation",
    )
    if credentials.kind == "anonymous":
        return {}
    if credentials.kind == "bearer":
        assert credentials.token is not None
        return {"Authorization": "Bearer " + credentials.token}

    assert credentials.username is not None
    assert credentials.password is not None
    token = base64.b64encode(
        f"{credentials.username}:{credentials.password}".encode("utf-8")
    ).decode("ascii")
    return {"Authorization": "Basic " + token}


def username_for_token(token: str, explicit_username: str | None) -> str:
    if explicit_username is not None:
        return explicit_username

    claims = decode_claims_unverified(token)
    for claim_name in ("preferred_username", "username", "upn", "email", "sub"):
        value = claims.get(claim_name)
        if isinstance(value, str) and value:
            return value

    return "oauth"


def _raise_credential_error(
    message: str,
    error_type: Literal["connection", "operation"],
    *,
    cause: Exception | None = None,
) -> NoReturn:
    error_cls = (
        TimeBaseConnectionError
        if error_type == "connection"
        else TimeBaseOperationStateError
    )
    if cause is None:
        raise error_cls(message)
    raise error_cls(message) from cause


def _discover_timebase_oauth_base_url(
    instance: TimeBaseInstanceRuntime,
    config: TimeBaseInstanceConfig,
) -> tuple[str | None, str | None]:
    try:
        endpoints = _resolve_interactive_endpoints(
            instance=instance,
            issuer_override=None,
            client_id_override=config.tb_oauth2_client_id,
            scope_override=config.tb_oauth2_scope,
        )
    except ConfigurationError as exc:
        logger.info(
            "TimeBase OAuth auto-discovery failed for %s. %s",
            config.tb_url,
            exc,
        )
        return None, str(exc)

    _maybe_enable_ssl_termination(config.tb_url, endpoints.discovery_base_url)
    return endpoints.discovery_base_url, None


def _resolve_interactive_endpoints(
    *,
    instance: TimeBaseInstanceRuntime,
    issuer_override: str | None,
    client_id_override: str | None,
    scope_override: str | None,
):
    from timebase_mcp.auth.discovery import resolve_interactive_endpoints

    return resolve_interactive_endpoints(
        instance=instance,
        issuer_override=issuer_override,
        client_id_override=client_id_override,
        scope_override=scope_override,
    )


def _select_auto_auth_mode(
    instance: TimeBaseInstanceRuntime,
    config: TimeBaseInstanceConfig,
    *,
    timebase_advertises_oauth: bool,
) -> OutboundAuthMode:
    if config.tb_password is not None:
        return "basic"

    if config.oauth2_config is not None:
        return "oauth2_client_credentials"

    if timebase_advertises_oauth:
        if (
            instance.runtime_auth_enabled
            and instance.runtime_is_http_transport
            and instance.runtime_inbound_auth_mode == "jwt"
        ):
            return "forward_identity"

        if instance.runtime_inbound_auth_mode == "api_key":
            raise ConfigurationError(
                "TimeBase advertises OAuth, but inbound MCP auth uses API keys. "
                "API-key callers cannot be forwarded to TimeBase. Configure "
                "TIMEBASE_AUTH_MODE=oauth2_client_credentials, basic, or none."
            )

        if instance.runtime_is_http_transport:
            raise ConfigurationError(
                "TimeBase advertises OAuth, but interactive login is only supported "
                "for stdio transport. Configure TIMEBASE_AUTH_MODE=forward_identity, "
                "oauth2_client_credentials, basic, or none."
            )

        return "interactive"

    return "none"


def _maybe_enable_ssl_termination(tb_url: str, discovery_base_url: str | None) -> None:
    if os.environ.get(DXAPI_SSL_TERMINATION_ENV) is not None:
        return
    if discovery_base_url is None:
        return

    discovery = urlparse(discovery_base_url)
    if discovery.scheme != "https":
        return

    tb = urlparse(tb_url)
    tb_authority = tb.netloc
    if discovery.netloc != tb_authority:
        return

    os.environ[DXAPI_SSL_TERMINATION_ENV] = "true"
    logger.info(
        "Enabled DXAPI_SSL_TERMINATION=true because TimeBase OAuth discovery "
        "succeeded over HTTPS on the dxtick endpoint."
    )
