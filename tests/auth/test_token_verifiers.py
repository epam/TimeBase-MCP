from __future__ import annotations

from pathlib import Path

import jwt
import pytest
from mcp.server.auth.middleware.auth_context import auth_context_var
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
from mcp.server.auth.provider import AccessToken

from tests.auth.helpers import (
    make_rsa_verifier,
)
from timebase_mcp.auth import keystore
from timebase_mcp.auth.keystore import KeyStore
from timebase_mcp.auth.principal import current_principal
from timebase_mcp.auth.token_verifier import (
    ApiKeyStoreVerifier,
    decode_claims_unverified,
    extract_scopes,
)
from timebase_mcp.config.env import SettingsEnv
from timebase_mcp.config.settings import MCPSettings


def test_required_scopes_normalization(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(SettingsEnv.MCP_AUTH_REQUIRED_SCOPES, "a b,c")

    settings = MCPSettings()

    assert settings.auth_required_scopes == ["a", "b", "c"]


def test_extract_scopes_supports_common_shapes() -> None:
    assert extract_scopes({"scope": "a b c"}) == ["a", "b", "c"]
    assert extract_scopes({"scp": ["x", "y"]}) == ["x", "y"]
    assert extract_scopes({}) == []


def test_decode_claims_unverified_returns_payload() -> None:
    token = jwt.encode(
        {"preferred_username": "alice"},
        "test-secret-key-that-is-long-enough-1234567890",
        algorithm="HS256",
    )

    claims = decode_claims_unverified(token)

    assert claims["preferred_username"] == "alice"


def test_decode_claims_unverified_handles_garbage() -> None:
    assert decode_claims_unverified("not-a-jwt") == {}


@pytest.mark.anyio
async def test_jwks_verifier_accepts_valid_token() -> None:
    verifier, private_key = make_rsa_verifier()
    token = jwt.encode(
        {
            "iss": "https://idp.example",
            "sub": "user-1",
            "azp": "mcp-client",
            "scope": "timebase.read",
            "preferred_username": "alice",
        },
        private_key,
        algorithm="RS256",
    )

    access = await verifier.verify_token(token)

    assert access is not None
    assert access.subject == "user-1"
    assert access.client_id == "mcp-client"
    assert access.scopes == ["timebase.read"]


@pytest.mark.anyio
async def test_jwks_verifier_rejects_wrong_issuer() -> None:
    verifier, private_key = make_rsa_verifier(issuer="https://idp.example")
    token = jwt.encode(
        {"iss": "https://evil.example", "sub": "user-1"},
        private_key,
        algorithm="RS256",
    )

    assert await verifier.verify_token(token) is None


@pytest.mark.anyio
async def test_jwks_verifier_enforces_required_scopes() -> None:
    verifier, private_key = make_rsa_verifier(required_scopes=["timebase.write"])
    token = jwt.encode(
        {"iss": "https://idp.example", "sub": "user-1", "scope": "timebase.read"},
        private_key,
        algorithm="RS256",
    )

    assert await verifier.verify_token(token) is None


def test_current_principal_none_without_context() -> None:
    assert current_principal() is None


def test_current_principal_reads_access_token() -> None:
    access = AccessToken(
        token="tok",
        client_id="cid",
        scopes=["s"],
        subject="user-1",
        claims={"preferred_username": "alice"},
    )
    reset = auth_context_var.set(AuthenticatedUser(access))
    try:
        principal = current_principal()
    finally:
        auth_context_var.reset(reset)

    assert principal is not None
    assert principal.subject == "user-1"
    assert principal.username == "alice"
    assert principal.token == "tok"


@pytest.mark.anyio
async def test_api_key_verifier_accepts_valid_key(tmp_path: Path) -> None:
    record, raw_key = keystore.build_record(name="alice", scopes=["timebase.read"])
    keys_file = tmp_path / "keys.json"
    keystore.write_store(keys_file, [record])
    verifier = ApiKeyStoreVerifier(KeyStore(keys_file))

    access = await verifier.verify_token(raw_key)

    assert access is not None
    assert access.subject == "alice"
    assert access.scopes == ["timebase.read"]
    assert access.claims is not None
    assert access.claims["preferred_username"] == "alice"


@pytest.mark.anyio
async def test_api_key_verifier_rejects_unknown_key(tmp_path: Path) -> None:
    record, _ = keystore.build_record(name="alice", scopes=[])
    keys_file = tmp_path / "keys.json"
    keystore.write_store(keys_file, [record])
    verifier = ApiKeyStoreVerifier(KeyStore(keys_file))

    assert await verifier.verify_token("tbk_unknown") is None


@pytest.mark.anyio
async def test_api_key_verifier_returns_per_key_identity(tmp_path: Path) -> None:
    r1, k1 = keystore.build_record(name="alice", scopes=["read"])
    r2, k2 = keystore.build_record(name="bob", scopes=["write"])
    keys_file = tmp_path / "keys.json"
    keystore.write_store(keys_file, [r1, r2])
    verifier = ApiKeyStoreVerifier(KeyStore(keys_file))

    a1 = await verifier.verify_token(k1)
    a2 = await verifier.verify_token(k2)

    assert a1 is not None and a1.subject == "alice" and a1.scopes == ["read"]
    assert a2 is not None and a2.subject == "bob" and a2.scopes == ["write"]


@pytest.mark.anyio
async def test_api_key_verifier_live_reload(tmp_path: Path) -> None:
    r1, k1 = keystore.build_record(name="alice", scopes=[])
    keys_file = tmp_path / "keys.json"
    keystore.write_store(keys_file, [r1])
    verifier = ApiKeyStoreVerifier(KeyStore(keys_file))

    assert await verifier.verify_token(k1) is not None

    r2, k2 = keystore.build_record(name="bob", scopes=[])
    keystore.write_store(keys_file, [r2])

    assert await verifier.verify_token(k1) is None
    assert await verifier.verify_token(k2) is not None


@pytest.mark.anyio
async def test_api_key_verifier_missing_file_rejects(tmp_path: Path) -> None:
    verifier = ApiKeyStoreVerifier(KeyStore(tmp_path / "missing.json"))

    assert await verifier.verify_token(keystore.generate_key()) is None


@pytest.mark.anyio
async def test_api_key_verifier_malformed_file_rejects(tmp_path: Path) -> None:
    keys_file = tmp_path / "bad.json"
    keys_file.write_text("not-valid-json", encoding="utf-8")
    verifier = ApiKeyStoreVerifier(KeyStore(keys_file))

    assert await verifier.verify_token(keystore.generate_key()) is None
