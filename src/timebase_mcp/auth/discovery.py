from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import httpx2

from timebase_mcp.errors import ConfigurationError
from timebase_mcp.clients.http.transport import (
    HTTP_DISCOVERY_TIMEOUT_SECONDS,
    tls_verify,
    timebase_http_request,
)

if TYPE_CHECKING:
    from timebase_mcp.runtime.instance import TimeBaseInstanceRuntime

logger = logging.getLogger(__name__)

_TB_CLIENT_APPLICATION = "timebase.client.application"


@dataclass(frozen=True, slots=True)
class OAuthInfo:
    """Subset of TimeBase's oauthinfo response."""

    issuer: str | None = None
    jwks_url: str | None = None
    authorization_endpoint: str | None = None
    token_endpoint: str | None = None
    client_id: str | None = None
    scope: str | None = None
    discovery_base_url: str | None = None


@dataclass(frozen=True, slots=True)
class ResolvedInboundAuth:
    issuer: str
    jwks_uri: str


@dataclass(frozen=True, slots=True)
class InteractiveEndpoints:
    authorization_endpoint: str
    token_endpoint: str
    client_id: str
    scope: str
    discovery_base_url: str | None = None


def _get_json(url: str, *, allow_empty: bool = False) -> dict[str, Any]:
    response = httpx2.get(
        url,
        timeout=HTTP_DISCOVERY_TIMEOUT_SECONDS,
        verify=tls_verify(),
    )
    response.raise_for_status()
    return _response_json(response, allow_empty=allow_empty, source=url)


def _response_json(
    response: httpx2.Response,
    *,
    allow_empty: bool = False,
    source: str | None = None,
) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError as exc:
        raw_content = getattr(response, "content", b"")
        if isinstance(raw_content, bytes) and allow_empty and not raw_content.strip():
            return {}
        content_type = response.headers.get("content-type", "<unknown>")
        location = source or _response_url(response)
        raise ConfigurationError(
            f"Expected JSON response from {location}, got invalid payload "
            f"(content-type: {content_type})."
        ) from exc
    if not isinstance(payload, dict):
        location = source or _response_url(response)
        raise ConfigurationError(f"Unexpected discovery response from {location}.")
    return payload


def _response_url(response: httpx2.Response) -> str:
    try:
        return str(response.url)
    except RuntimeError:
        return "<unknown>"


def _first_str(payload: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _app_entry_value(
    value: object,
    value_key: str,
    *,
    app_name: str = _TB_CLIENT_APPLICATION,
) -> str | None:
    if not isinstance(value, list):
        return None

    entries = [item for item in value if isinstance(item, dict)]
    if len(entries) == 1 and entries[0].get("app") is None:
        selected = entries[0].get(value_key)
        return selected if isinstance(selected, str) and selected else None

    for entry in entries:
        app = entry.get("app")
        selected = entry.get(value_key)
        if (
            isinstance(app, str)
            and app.casefold() == app_name.casefold()
            and isinstance(selected, str)
            and selected
        ):
            return selected

    return None


def _client_id(payload: dict[str, Any]) -> str | None:
    return _first_str(payload, "clientId", "client_id", "clientID") or _app_entry_value(
        payload.get("clientid"),
        "name",
    )


def _scope(payload: dict[str, Any]) -> str | None:
    return _app_entry_value(payload.get("scopes"), "scope") or _first_str(
        payload, "scope", "scopes"
    )


def fetch_oauthinfo(instance: TimeBaseInstanceRuntime) -> OAuthInfo:
    try:
        response = timebase_http_request(instance, "/oauthinfo", auth=False)
        payload = _response_json(response, allow_empty=True)
    except httpx2.HTTPError as exc:
        raise ConfigurationError(
            f"Failed to fetch TimeBase OAuth metadata for instance "
            f"'{instance.key}': {exc}"
        ) from exc

    return OAuthInfo(
        issuer=_first_str(payload, "issuer", "issuerUrl", "issuer_url"),
        jwks_url=_first_str(payload, "jwksUrl", "jwks_uri", "jwksUri", "jwks_url"),
        authorization_endpoint=_first_str(
            payload, "authorizationEndpoint", "authorization_endpoint", "authorizeUrl"
        ),
        token_endpoint=_first_str(
            payload, "tokenEndpoint", "token_endpoint", "tokenUrl"
        ),
        client_id=_client_id(payload),
        scope=_scope(payload),
        discovery_base_url=instance.resolved_http_base_url,
    )


def fetch_oidc_metadata(issuer: str) -> dict[str, Any]:
    url = issuer.rstrip("/") + "/.well-known/openid-configuration"
    try:
        return _get_json(url)
    except httpx2.HTTPError as exc:
        raise ConfigurationError(
            f"Failed to fetch OpenID configuration from {url}: {exc}"
        ) from exc


def resolve_inbound_auth(
    *,
    issuer_override: str | None,
    jwks_override: str | None,
    instance: TimeBaseInstanceRuntime | None,
) -> ResolvedInboundAuth:
    """Resolve the issuer + JWKS URL for inbound token verification.

    Prefers explicit overrides; otherwise discovers them from TimeBase's
    ``/tb/oauthinfo`` and, if needed, the IdP's OpenID configuration.
    """
    issuer = issuer_override
    jwks_uri = jwks_override

    info: OAuthInfo | None = None
    if (issuer is None or jwks_uri is None) and instance is not None:
        info = fetch_oauthinfo(instance)

    if issuer is None:
        issuer = info.issuer if info is not None else None
    if issuer is None:
        raise ConfigurationError(
            "Cannot resolve the inbound OAuth issuer. Set MCP_AUTH_ISSUER_URL or "
            "configure a reachable TimeBase HTTP base URL (http_base_url) for "
            "discovery."
        )

    if jwks_uri is None and info is not None:
        jwks_uri = info.jwks_url
    if jwks_uri is None:
        metadata = fetch_oidc_metadata(issuer)
        jwks_uri = _first_str(metadata, "jwks_uri")
    if jwks_uri is None:
        raise ConfigurationError(
            "Cannot resolve the JWKS URL for inbound token verification. Set "
            "MCP_AUTH_JWKS_URL explicitly."
        )

    return ResolvedInboundAuth(issuer=issuer, jwks_uri=jwks_uri)


def resolve_interactive_endpoints(
    *,
    instance: TimeBaseInstanceRuntime | None,
    issuer_override: str | None,
    client_id_override: str | None,
    scope_override: str | None,
) -> InteractiveEndpoints:
    """Resolve authorize/token endpoints + client id for interactive login."""
    info: OAuthInfo | None = None
    discovery_error: ConfigurationError | None = None
    if instance is not None:
        try:
            info = fetch_oauthinfo(instance)
        except ConfigurationError as exc:
            discovery_error = exc
            logger.debug("TimeBase oauthinfo discovery failed.", exc_info=True)

    issuer = issuer_override or (info.issuer if info is not None else None)
    authorization_endpoint = info.authorization_endpoint if info is not None else None
    token_endpoint = info.token_endpoint if info is not None else None

    if (
        authorization_endpoint is None or token_endpoint is None
    ) and issuer is not None:
        metadata = fetch_oidc_metadata(issuer)
        authorization_endpoint = authorization_endpoint or _first_str(
            metadata, "authorization_endpoint"
        )
        token_endpoint = token_endpoint or _first_str(metadata, "token_endpoint")

    if authorization_endpoint is None or token_endpoint is None:
        message = (
            "Cannot resolve interactive OAuth endpoints. Configure the TimeBase "
            "HTTP base URL (http_base_url) or TIMEBASE_OAUTH2_TOKEN_URL."
        )
        if discovery_error is not None:
            raise ConfigurationError(
                f"{message} {discovery_error}"
            ) from discovery_error
        raise ConfigurationError(message)

    client_id = client_id_override or (info.client_id if info is not None else None)
    if client_id is None:
        message = (
            "Interactive login requires an OAuth client id. Set "
            "TIMEBASE_OAUTH2_CLIENT_ID or ensure TimeBase advertises one via "
            "/tb/oauthinfo."
        )
        if discovery_error is not None:
            raise ConfigurationError(
                f"{message} {discovery_error}"
            ) from discovery_error
        raise ConfigurationError(message)

    scope = scope_override or (info.scope if info is not None else None) or "openid"

    return InteractiveEndpoints(
        authorization_endpoint=authorization_endpoint,
        token_endpoint=token_endpoint,
        client_id=client_id,
        scope=scope,
        discovery_base_url=info.discovery_base_url if info is not None else None,
    )
