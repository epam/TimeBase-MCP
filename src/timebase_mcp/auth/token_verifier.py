from __future__ import annotations

import asyncio
import hmac
import logging
from collections.abc import Iterable, Sequence
from typing import Any

import jwt
from mcp.server.auth.provider import AccessToken, TokenVerifier

from timebase_mcp.auth.keystore import ApiKeyRecord, KeyStore, hash_key

logger = logging.getLogger(__name__)

_DEFAULT_ALGORITHMS: tuple[str, ...] = ("RS256",)


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

    Verifies the signature, expiry and issuer and audience when configured,
    then maps the standard claims onto an ``AccessToken`` the MCP SDK can use.
    """

    def __init__(
        self,
        *,
        jwks_uri: str,
        issuer: str,
        audience: str | None = None,
        required_scopes: Sequence[str] | None = None,
        algorithms: Iterable[str] = _DEFAULT_ALGORITHMS,
        client_id_claim: str = "azp",
    ) -> None:
        self._jwks_client = jwt.PyJWKClient(jwks_uri, cache_keys=True)
        self._issuer = issuer
        self._audience = audience
        self._required_scopes = list(required_scopes or [])
        self._algorithms = list(algorithms)
        self._client_id_claim = client_id_claim

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            return await asyncio.to_thread(self._verify_sync, token)
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
            options={"verify_aud": self._audience is not None},
        )

        scopes = extract_scopes(claims)
        if self._required_scopes and not set(self._required_scopes).issubset(scopes):
            logger.debug(
                "Inbound token missing required scopes %s.", self._required_scopes
            )
            return None

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

    async def verify_token(self, token: str) -> AccessToken | None:
        return await asyncio.to_thread(self._verify_sync, token)

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
