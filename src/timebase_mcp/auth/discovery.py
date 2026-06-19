from __future__ import annotations

import logging
import os
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import httpx

from timebase_mcp.errors import ConfigurationError

logger = logging.getLogger(__name__)

_DISCOVERY_TIMEOUT_SECONDS = 3.0
_AUTHORITY_RE = re.compile(r"^[a-zA-Z0-9.+-]+://([^/?#]+)")
_SCHEME_RE = re.compile(r"^([a-zA-Z0-9.+-]+)://")
_SSL_SCHEMES = frozenset({"dstick", "dsctick"})
_DXAPI_SSL_TERMINATION_ENV = "DXAPI_SSL_TERMINATION"
_DXAPI_SSL_TRUST_ALL_ENV = "DXAPI_SSL_TRUST_ALL"
_TB_CLIENT_APPLICATION = "timebase.client.application"
_trust_all_warning_emitted = False


@dataclass(frozen=True, slots=True)
class OAuthInfo:
    """Subset of TimeBase's ``GET /tb/oauthinfo`` response."""

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


def _env_true(name: str) -> bool:
    return os.environ.get(name, "").casefold() == "true"


def derive_http_base_url(tb_url: str) -> str | None:
    """Best-effort HTTP base URL for OAuth discovery from a TB URL.

    The TimeBase HTTP API (which serves ``/tb/oauthinfo``) may listen on a
    different port than the binary protocol, so this is only a fallback used when
    no explicit ``http_base_url`` is configured.
    """
    urls = derive_http_base_urls(tb_url)
    return urls[0] if urls else None


def derive_http_base_urls(tb_url: str) -> tuple[str, ...]:
    """Best-effort ordered HTTP base URL candidates for OAuth discovery."""
    match = _AUTHORITY_RE.match(tb_url)
    if match is None:
        return ()

    authority = match.group(1)
    # Cluster URLs look like ``host1:8011|host2:8011``, use the first node
    first_node = authority.split("|", 1)[0].strip()
    if not first_node:
        return ()

    scheme_match = _SCHEME_RE.match(tb_url)
    scheme = scheme_match.group(1).casefold() if scheme_match is not None else ""
    https_first = _env_true(_DXAPI_SSL_TERMINATION_ENV) or scheme in _SSL_SCHEMES
    schemes = ("https", "http") if https_first else ("http", "https")
    return tuple(f"{http_scheme}://{first_node}" for http_scheme in schemes)


def _httpx_verify() -> bool:
    if not _env_true(_DXAPI_SSL_TRUST_ALL_ENV):
        return True

    global _trust_all_warning_emitted
    if not _trust_all_warning_emitted:
        logger.warning(
            "DXAPI_SSL_TRUST_ALL=true disables TLS certificate verification for "
            "OAuth discovery. This weakens issuer/JWKS/token endpoint trust."
        )
        _trust_all_warning_emitted = True
    return False


def _get_json(url: str, *, allow_empty: bool = False) -> dict[str, Any]:
    response = httpx.get(
        url,
        timeout=_DISCOVERY_TIMEOUT_SECONDS,
        verify=_httpx_verify(),
    )
    response.raise_for_status()
    try:
        payload = response.json()
    except ValueError as exc:
        raw_content = getattr(response, "content", b"")
        if isinstance(raw_content, bytes) and allow_empty and not raw_content.strip():
            return {}
        content_type = response.headers.get("content-type", "<unknown>")
        raise ConfigurationError(
            f"Expected JSON response from {url}, got invalid payload "
            f"(content-type: {content_type})."
        ) from exc
    if not isinstance(payload, dict):
        raise ConfigurationError(f"Unexpected discovery response from {url}.")
    return payload


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


def _base_url_candidates(
    discovery_base_url: str | Sequence[str] | None,
) -> tuple[str, ...]:
    if discovery_base_url is None:
        return ()
    if isinstance(discovery_base_url, str):
        candidates = (discovery_base_url,)
    else:
        candidates = tuple(discovery_base_url)

    deduplicated: list[str] = []
    for candidate in candidates:
        normalized = candidate.rstrip("/")
        if normalized and normalized not in deduplicated:
            deduplicated.append(normalized)
    return tuple(deduplicated)


def fetch_oauthinfo(http_base_url: str) -> OAuthInfo:
    base_url = http_base_url.rstrip("/")
    url = base_url + "/tb/oauthinfo"
    try:
        payload = _get_json(url, allow_empty=True)
    except httpx.HTTPError as exc:
        raise ConfigurationError(
            f"Failed to fetch TimeBase OAuth metadata from {url}: {exc}"
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
        discovery_base_url=base_url,
    )


def fetch_oauthinfo_from_candidates(
    discovery_base_url: str | Sequence[str] | None,
) -> OAuthInfo:
    candidates = _base_url_candidates(discovery_base_url)
    if not candidates:
        raise ConfigurationError(
            "Cannot fetch TimeBase OAuth metadata because no TimeBase HTTP base URL "
            "could be derived. Set TIMEBASE_HTTP_URL."
        )

    errors: list[str] = []
    for candidate in candidates:
        try:
            return fetch_oauthinfo(candidate)
        except ConfigurationError as exc:
            errors.append(str(exc))
            logger.debug(
                "TimeBase oauthinfo discovery failed for %s.", candidate, exc_info=True
            )

    attempted = ", ".join(candidate + "/tb/oauthinfo" for candidate in candidates)
    detail = errors[-1] if errors else "unknown error"
    raise ConfigurationError(
        f"Failed to fetch TimeBase OAuth metadata. Tried: {attempted}. Last error: {detail}"
    )


def fetch_oidc_metadata(issuer: str) -> dict[str, Any]:
    url = issuer.rstrip("/") + "/.well-known/openid-configuration"
    try:
        return _get_json(url)
    except httpx.HTTPError as exc:
        raise ConfigurationError(
            f"Failed to fetch OpenID configuration from {url}: {exc}"
        ) from exc


def resolve_inbound_auth(
    *,
    issuer_override: str | None,
    jwks_override: str | None,
    discovery_base_url: str | Sequence[str] | None,
) -> ResolvedInboundAuth:
    """Resolve the issuer + JWKS URL for inbound token verification.

    Prefers explicit overrides; otherwise discovers them from TimeBase's
    ``/tb/oauthinfo`` and, if needed, the IdP's OpenID configuration.
    """
    issuer = issuer_override
    jwks_uri = jwks_override

    info: OAuthInfo | None = None
    if (issuer is None or jwks_uri is None) and discovery_base_url is not None:
        info = fetch_oauthinfo_from_candidates(discovery_base_url)

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
    discovery_base_url: str | Sequence[str] | None,
    issuer_override: str | None,
    client_id_override: str | None,
    scope_override: str | None,
) -> InteractiveEndpoints:
    """Resolve authorize/token endpoints + client id for interactive login."""
    info: OAuthInfo | None = None
    discovery_error: ConfigurationError | None = None
    if discovery_base_url is not None:
        try:
            info = fetch_oauthinfo_from_candidates(discovery_base_url)
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
