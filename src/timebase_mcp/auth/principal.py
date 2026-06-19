from __future__ import annotations

from dataclasses import dataclass

from mcp.server.auth.middleware.auth_context import get_access_token


@dataclass(frozen=True, slots=True)
class Principal:
    """The authenticated MCP caller resolved from the inbound bearer token."""

    subject: str
    token: str
    client_id: str | None = None
    username: str | None = None
    scopes: tuple[str, ...] = ()


def current_principal() -> Principal | None:
    """Return the principal for the in-flight request, if inbound auth ran.

    Returns ``None`` for unauthenticated transports (stdio) or when inbound auth
    is disabled, since the auth middleware does not populate the context then.
    """
    access_token = get_access_token()
    if access_token is None:
        return None

    claims = access_token.claims or {}
    username = (
        claims.get("preferred_username")
        or claims.get("username")
        or claims.get("upn")
        or claims.get("email")
        or access_token.subject
    )
    subject = access_token.subject or access_token.client_id or access_token.token

    return Principal(
        subject=str(subject),
        token=access_token.token,
        client_id=access_token.client_id,
        username=str(username) if username is not None else None,
        scopes=tuple[str, ...](access_token.scopes or ()),
    )
