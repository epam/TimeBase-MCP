from __future__ import annotations

from collections.abc import Sequence

from mcp.server.auth.settings import AuthSettings
from pydantic import AnyHttpUrl, TypeAdapter

_HTTP_URL_ADAPTER = TypeAdapter(AnyHttpUrl)


def _to_http_url(value: str) -> AnyHttpUrl:
    return _HTTP_URL_ADAPTER.validate_python(value)


def build_auth_settings(
    *,
    issuer_url: str,
    resource_server_url: str | None,
    required_scopes: Sequence[str] | None = None,
) -> AuthSettings:
    """Build the MCP SDK ``AuthSettings`` for inbound auth."""
    return AuthSettings(
        issuer_url=_to_http_url(issuer_url),
        resource_server_url=(
            _to_http_url(resource_server_url)
            if resource_server_url is not None
            else None
        ),
        required_scopes=list(required_scopes) if required_scopes else None,
    )
