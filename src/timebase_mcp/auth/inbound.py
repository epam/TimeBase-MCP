from __future__ import annotations

import logging
from dataclasses import dataclass

from mcp.server.auth.provider import TokenVerifier
from mcp.server.auth.settings import AuthSettings

from timebase_mcp.auth.discovery import (
    derive_http_base_urls,
    resolve_inbound_auth,
)
from timebase_mcp.auth.keystore import KeyStore
from timebase_mcp.auth.settings import build_auth_settings
from timebase_mcp.auth.token_verifier import ApiKeyStoreVerifier, JwksTokenVerifier
from timebase_mcp.config import MCPSettings

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class InboundAuth:
    auth_settings: AuthSettings
    token_verifier: TokenVerifier


def _public_url(settings: MCPSettings) -> str:
    if settings.auth_public_url is not None:
        return settings.auth_public_url
    return f"http://{settings.host}:{settings.port}"


def _discovery_base_url(settings: MCPSettings) -> str | tuple[str, ...] | None:
    servers = settings.resolve_servers()
    default_key = settings.resolved_default_instance_key
    ordered = sorted(servers, key=lambda server: server.instance_key != default_key)
    for server in ordered:
        base = server.http_base_url or derive_http_base_urls(server.url)
        if base:
            return base
    return None


def build_inbound_auth(settings: MCPSettings) -> InboundAuth | None:
    """Build inbound Resource Server auth, or ``None`` when disabled.

    Inbound auth is only meaningful for HTTP transports; the caller is expected
    to skip it for stdio.
    """
    if not settings.inbound_auth_enabled:
        return None

    public_url = _public_url(settings)
    required_scopes = settings.auth_required_scopes

    if settings.auth_api_keys_file:
        logger.info(
            "Inbound auth enabled using the API key store at %s ",
            settings.auth_api_keys_file,
        )
        return InboundAuth(
            auth_settings=build_auth_settings(
                issuer_url=settings.auth_issuer_url or public_url,
                resource_server_url=None,  # avoid publishing protected-resource metadata
                required_scopes=required_scopes,
            ),
            token_verifier=ApiKeyStoreVerifier(KeyStore(settings.auth_api_keys_file)),
        )

    resolved = resolve_inbound_auth(
        issuer_override=settings.auth_issuer_url,
        jwks_override=settings.auth_jwks_url,
        discovery_base_url=_discovery_base_url(settings),
    )
    logger.info(
        "Inbound auth enabled (Resource Server). issuer=%s jwks=%s",
        resolved.issuer,
        resolved.jwks_uri,
    )
    return InboundAuth(
        auth_settings=build_auth_settings(
            issuer_url=resolved.issuer,
            resource_server_url=public_url,
            required_scopes=required_scopes,
        ),
        token_verifier=JwksTokenVerifier(
            jwks_uri=resolved.jwks_uri,
            issuer=resolved.issuer,
            audience=settings.auth_audience,
            required_scopes=required_scopes,
        ),
    )
