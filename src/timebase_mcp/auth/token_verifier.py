from __future__ import annotations

import hmac
import logging
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

import jwt
from anyio import CapacityLimiter
from anyio.to_thread import run_sync
from mcp.server.auth.provider import AccessToken, TokenVerifier
from typing_extensions import override

from timebase_mcp.auth.keystore import ApiKeyRecord, KeyStore, hash_key
from timebase_mcp.auth.scopes import is_scope_token

logger = logging.getLogger(__name__)

_DEFAULT_ALGORITHMS: tuple[str, ...] = ("RS256",)
# Match AnyIO's worker limit, with capacity reserved for authentication.
_AUTH_WORKER_LIMIT = 40


def extract_scopes(claims: dict[str, Any]) -> list[str]:
    """Read OAuth scopes from the common claim shapes (``scope``/``scp``)."""
    scope_value = claims.get("scope")
    if isinstance(scope_value, str):
        return [token for token in scope_value.split() if token]

    for claim_name in ("scp", "scopes", "roles"):
        value = claims.get(claim_name)
        if isinstance(value, list):
            return [str(item) for item in value]
        if isinstance(value, str):
            return [token for token in value.split() if token]

    return []


def decode_claims_unverified(token: str) -> dict[str, Any]:
    """Decode a JWT payload without signature verification (for display only)."""
    try:
        claims = jwt.decode(token, options={"verify_signature": False})
    except jwt.PyJWTError:
        return {}
    return claims if isinstance(claims, dict) else {}


class JwksTokenVerifier(TokenVerifier):
    """Validate inbound JWT bearer tokens against an IdP's JWKS endpoint.

    Requires expiration and verifies the signature, issuer and configured audience,
    then maps the standard claims onto an ``AccessToken`` the MCP SDK can use.
    """

    def __init__(
        self,
        *,
        jwks_uri: str,
        issuer: str,
        audience: str | None = None,
        required_scopes: Sequence[str] | None = None,
        scope_aliases: Mapping[str, str] | None = None,
        algorithms: Iterable[str] = _DEFAULT_ALGORITHMS,
        client_id_claim: str = "azp",
    ) -> None:
        # Keep only the expiring JWKS cache so removed keys are forgotten.
        self._jwks_client = jwt.PyJWKClient(jwks_uri)
        self._issuer = issuer
        self._audience = audience
        self._required_scopes = list(required_scopes or [])
        self._scope_aliases = dict(scope_aliases or {})
        self._algorithms = list(algorithms)
        self._client_id_claim = client_id_claim
        self._worker_limiter = CapacityLimiter(_AUTH_WORKER_LIMIT)

    @override
    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            return await run_sync(
                self._verify_sync, token, limiter=self._worker_limiter
            )
        except Exception:
            logger.debug("Inbound token verification failed.", exc_info=True)
            return None

    def _verify_sync(self, token: str) -> AccessToken | None:
        signing_key = self._jwks_client.get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=self._algorithms,
            audience=self._audience,
            issuer=self._issuer,
            options={"verify_aud": self._audience is not None, "require": ["exp"]},
        )

        scopes = extract_scopes(claims)
        scp = claims.get("scp")
        delegated_scopes = scp.split(" ") if isinstance(scp, str) else []
        if not all(is_scope_token(scope) for scope in delegated_scopes):
            delegated_scopes = []
        for required in self._required_scopes:
            alias = self._scope_aliases.get(required)
            available = delegated_scopes if alias is not None else scopes
            if (alias if alias is not None else required) not in available:
                logger.debug("Inbound token missing required scope %s.", required)
                return None

        # SDK middleware checks advertised names, forwarding keeps the original JWT
        for required in self._required_scopes:
            if required in self._scope_aliases and required not in scopes:
                scopes.append(required)

        subject = claims.get("sub")
        client_id = (
            claims.get(self._client_id_claim)
            or claims.get("client_id")
            or claims.get("sub")
        )

        return AccessToken(
            token=token,
            client_id=str(client_id) if client_id is not None else "",
            scopes=scopes,
            expires_at=claims.get("exp"),
            subject=str(subject) if subject is not None else None,
            claims=claims,
        )


class ApiKeyStoreVerifier(TokenVerifier):
    """Verify inbound bearer tokens against a hashed API key store."""

    def __init__(self, store: KeyStore) -> None:
        self._store = store
        self._worker_limiter = CapacityLimiter(_AUTH_WORKER_LIMIT)

    @override
    async def verify_token(self, token: str) -> AccessToken | None:
        return await run_sync(self._verify_sync, token, limiter=self._worker_limiter)

    def _verify_sync(self, token: str) -> AccessToken | None:
        token_hash = hash_key(token)
        matched: ApiKeyRecord | None = None
        # Compare against every record to avoid leaking which key
        # matched via timing.
        for record in self._store.records():
            if hmac.compare_digest(token_hash, record.hash):
                matched = record
        if matched is None:
            return None

        return AccessToken(
            token=token,
            client_id=matched.id,
            scopes=list(matched.scopes),
            subject=matched.name,
            claims={"preferred_username": matched.name},
        )
