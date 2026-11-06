from __future__ import annotations

from pathlib import Path
from time import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
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

_MCP_SCOPE = "https://mcp.example.com/mcp/mcp.access"


@pytest.fixture
def jwt_claims() -> dict[str, object]:
    return {
        "iss": "https://idp.example",
        "aud": "shared-api",
        "sub": "user-1",
        "azp": "mcp-client",
        "preferred_username": "alice",
        "exp": int(time()) + 3600,
    }


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
            "exp": int(time()) + 3600,
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
        {"iss": "https://evil.example", "sub": "user-1", "exp": int(time()) + 3600},
        private_key,
        algorithm="RS256",
    )

    assert await verifier.verify_token(token) is None


@pytest.mark.anyio
async def test_jwks_verifier_enforces_required_scopes() -> None:
    verifier, private_key = make_rsa_verifier(required_scopes=["timebase.write"])
    token = jwt.encode(
        {
            "iss": "https://idp.example",
            "sub": "user-1",
            "scope": "timebase.read",
            "exp": int(time()) + 3600,
        },
        private_key,
        algorithm="RS256",
    )

    assert await verifier.verify_token(token) is None


@pytest.mark.anyio
async def test_scope_alias_exposes_canonical_permission_without_changing_jwt(
    jwt_claims: dict[str, object],
) -> None:
    verifier, private_key = make_rsa_verifier(
        audience="shared-api",
        required_scopes=[_MCP_SCOPE],
        scope_aliases={_MCP_SCOPE: "mcp.access"},
    )
    jwt_claims.update({"scope": "legacy.read", "scp": "mcp.access another.permission"})
    token = jwt.encode(jwt_claims, private_key, algorithm="RS256")

    access = await verifier.verify_token(token)

    assert access is not None
    assert access.token == token
    assert access.claims == jwt_claims
    assert access.scopes == ["legacy.read", _MCP_SCOPE]
    assert access.expires_at == jwt_claims["exp"]


@pytest.mark.anyio
@pytest.mark.parametrize(
    "scope_claims",
    [
        {},
        {"scp": "other.permission"},
        {"scp": ""},
        {"scp": ["mcp.access"]},
        {"scp": {"mcp.access": True}},
        {"scp": 1},
        {"scp": "mcp.access\tother.permission"},
        {"scp": " mcp.access"},
        {"scp": "mcp.access "},
        {"scp": "mcp.access  other.permission"},
        {"scp": 'mcp.access bad"permission'},
        {"scope": _MCP_SCOPE},
        {"roles": [_MCP_SCOPE]},
        {"roles": ["mcp.access"]},
        {"scope": _MCP_SCOPE, "scp": "other.permission"},
        {"roles": [_MCP_SCOPE], "scp": "other.permission"},
    ],
)
async def test_scope_alias_requires_original_delegated_string_claim(
    jwt_claims: dict[str, object], scope_claims: dict[str, object]
) -> None:
    verifier, private_key = make_rsa_verifier(
        audience="shared-api",
        required_scopes=[_MCP_SCOPE],
        scope_aliases={_MCP_SCOPE: "mcp.access"},
    )
    jwt_claims.update(scope_claims)
    token = jwt.encode(jwt_claims, private_key, algorithm="RS256")

    assert await verifier.verify_token(token) is None


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("scp", "generic_scope", "accepted"),
    [
        ("mcp.read", "legacy.read", False),
        ("mcp.read mcp.write", "legacy.read", True),
        ("mcp.read mcp.write", "other.permission", False),
    ],
)
async def test_scope_aliases_require_all_mapped_and_unmapped_permissions(
    jwt_claims: dict[str, object], scp: str, generic_scope: str, accepted: bool
) -> None:
    verifier, private_key = make_rsa_verifier(
        required_scopes=["api/mcp.read", "api/mcp.write", "legacy.read"],
        scope_aliases={"api/mcp.read": "mcp.read", "api/mcp.write": "mcp.write"},
    )
    jwt_claims.update({"scp": scp, "scope": generic_scope})
    token = jwt.encode(jwt_claims, private_key, algorithm="RS256")

    access = await verifier.verify_token(token)

    assert (access is not None) is accepted
    if access is not None:
        assert access.scopes == ["legacy.read", "api/mcp.read", "api/mcp.write"]


@pytest.mark.anyio
async def test_scope_aliases_do_not_chain(jwt_claims: dict[str, object]) -> None:
    verifier, private_key = make_rsa_verifier(
        required_scopes=["scope.b", "scope.a"],
        scope_aliases={"scope.b": "mcp.access", "scope.a": "scope.b"},
    )
    jwt_claims["scp"] = "mcp.access"
    token = jwt.encode(jwt_claims, private_key, algorithm="RS256")

    assert await verifier.verify_token(token) is None


@pytest.mark.anyio
@pytest.mark.parametrize(
    "scope_claims",
    [{"scope": "legacy.read"}, {"scp": ["legacy.read"]}, {"roles": ["legacy.read"]}],
)
async def test_empty_scope_aliases_preserve_generic_claim_matching(
    jwt_claims: dict[str, object], scope_claims: dict[str, object]
) -> None:
    verifier, private_key = make_rsa_verifier(
        required_scopes=["legacy.read"], scope_aliases={}
    )
    jwt_claims.update(scope_claims)
    token = jwt.encode(jwt_claims, private_key, algorithm="RS256")

    access = await verifier.verify_token(token)

    assert access is not None
    assert access.scopes == ["legacy.read"]


@pytest.mark.anyio
@pytest.mark.parametrize(
    "invalid_claims",
    [
        {"iss": "https://other.example"},
        {"aud": "another-api"},
        {"exp": 0},
        {"exp": None},
    ],
)
async def test_scope_alias_does_not_bypass_jwt_validation(
    jwt_claims: dict[str, object], invalid_claims: dict[str, object]
) -> None:
    verifier, private_key = make_rsa_verifier(
        audience="shared-api",
        required_scopes=[_MCP_SCOPE],
        scope_aliases={_MCP_SCOPE: "mcp.access"},
    )
    jwt_claims.update({"scp": "mcp.access", **invalid_claims})
    token = jwt.encode(jwt_claims, private_key, algorithm="RS256")

    assert await verifier.verify_token(token) is None


@pytest.mark.anyio
async def test_scope_alias_does_not_bypass_signature_validation(
    jwt_claims: dict[str, object],
) -> None:
    verifier, _ = make_rsa_verifier(
        audience="shared-api",
        required_scopes=[_MCP_SCOPE],
        scope_aliases={_MCP_SCOPE: "mcp.access"},
    )
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwt_claims["scp"] = "mcp.access"
    token = jwt.encode(jwt_claims, other_key, algorithm="RS256")

    assert await verifier.verify_token(token) is None


@pytest.mark.anyio
@pytest.mark.parametrize("aliases", [{}, {_MCP_SCOPE: "mcp.access"}])
async def test_jwks_verifier_requires_expiration(
    jwt_claims: dict[str, object], aliases: dict[str, str]
) -> None:
    verifier, private_key = make_rsa_verifier(
        required_scopes=[_MCP_SCOPE] if aliases else None,
        scope_aliases=aliases,
    )
    jwt_claims.pop("exp")
    jwt_claims["scp"] = "mcp.access"
    token = jwt.encode(jwt_claims, private_key, algorithm="RS256")

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
    assert access.expires_at is None
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
