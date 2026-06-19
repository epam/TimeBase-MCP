from __future__ import annotations

import json
import logging
import os
import types
from pathlib import Path

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from mcp.server.auth.middleware.auth_context import auth_context_var
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
from mcp.server.auth.provider import AccessToken
from pydantic import ValidationError

from timebase_mcp.auth import keystore
import timebase_mcp.auth.discovery as discovery_module
from timebase_mcp.auth.discovery import (
    InteractiveEndpoints,
    derive_http_base_url,
    derive_http_base_urls,
    fetch_oauthinfo,
    resolve_interactive_endpoints,
)
from timebase_mcp.auth.inbound import build_inbound_auth
from timebase_mcp.auth.interactive import (
    InteractiveOAuthProvider,
    resolve_interactive_redirect_uri,
)
from timebase_mcp.auth.keystore import KeyStore
from timebase_mcp.auth.principal import current_principal
from timebase_mcp.auth.token_verifier import (
    ApiKeyStoreVerifier,
    JwksTokenVerifier,
    decode_claims_unverified,
    extract_scopes,
)
from timebase_mcp.clients.enterprise import EnterpriseTimeBaseClient
from timebase_mcp.clients.factory import create_timebase_client
from timebase_mcp.config import MCPSettings, SettingsEnv
from timebase_mcp.errors import ConfigurationError, TimeBaseOperationStateError
from timebase_mcp.instance import TimeBaseInstanceConfig
from timebase_mcp.operations import run_with_runtime
from timebase_mcp.runtime import build_runtime


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def test_servers_json_is_parsed_and_default_resolved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        SettingsEnv.TIMEBASE_SERVERS,
        json.dumps(
            [
                {"name": "prod", "url": "dxtick://prod:8011", "auth_mode": "none"},
                {"name": "dev", "url": "dxtick://u:p@dev:8011"},
            ]
        ),
    )

    settings = MCPSettings()
    servers = settings.resolve_servers()

    assert [server.instance_key for server in servers] == ["prod", "dev"]
    assert [server.name for server in servers] == ["prod", "dev"]
    assert servers[0].auth_mode == "none"
    assert servers[1].auth_mode == "basic"
    assert servers[1].username == "u"
    assert servers[1].password is not None
    assert servers[1].password.get_secret_value() == "p"
    assert settings.resolved_default_instance_key == "prod"


def test_servers_use_sanitized_url_as_key_when_name_is_omitted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        SettingsEnv.TIMEBASE_SERVERS,
        json.dumps([{"url": "dxtick://u:p@prod:8011", "description": "Production"}]),
    )

    settings = MCPSettings()
    server = settings.resolve_servers()[0]

    assert server.instance_key == "dxtick://prod:8011"
    assert server.name is None
    assert server.description == "Production"
    assert server.url == "dxtick://prod:8011"
    assert settings.resolved_default_instance_key == "dxtick://prod:8011"


def test_servers_use_name_as_key_when_specified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        SettingsEnv.TIMEBASE_SERVERS,
        json.dumps(
            [
                {
                    "name": "prod",
                    "description": "Production TimeBase",
                    "url": "dxtick://prod:8011",
                },
                {"url": "dxtick://dev:8011"},
            ]
        ),
    )

    settings = MCPSettings()
    servers = settings.resolve_servers()

    assert [server.instance_key for server in servers] == ["prod", "dxtick://dev:8011"]
    assert servers[0].name == "prod"
    assert servers[1].name is None
    assert servers[0].description == "Production TimeBase"
    assert settings.resolved_default_instance_key == "prod"


def test_servers_reject_duplicate_resolved_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        SettingsEnv.TIMEBASE_SERVERS,
        json.dumps(
            [
                {"url": "dxtick://prod:8011"},
                {"url": "dxtick://prod:8011"},
            ]
        ),
    )

    with pytest.raises(ValidationError, match="instance names must be unique"):
        MCPSettings()


def test_servers_url_only_defaults_to_auto(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        SettingsEnv.TIMEBASE_SERVERS,
        json.dumps([{"name": "prod", "url": "dxtick://prod:8011"}]),
    )

    settings = MCPSettings()

    assert settings.resolve_servers()[0].auth_mode == "auto"


def test_server_explicit_auto_allows_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        SettingsEnv.TIMEBASE_SERVERS,
        json.dumps(
            [
                {
                    "name": "prod",
                    "url": "dxtick://prod:8011",
                    "auth_mode": "auto",
                    "username": "u",
                    "password": "p",
                }
            ]
        ),
    )

    settings = MCPSettings()

    server = settings.resolve_servers()[0]
    assert server.auth_mode == "auto"
    assert server.username == "u"
    assert server.password is not None


def test_server_explicit_auto_allows_oauth2(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        SettingsEnv.TIMEBASE_SERVERS,
        json.dumps(
            [
                {
                    "name": "prod",
                    "url": "dxtick://prod:8011",
                    "auth_mode": "auto",
                    "oauth2_token_url": "https://idp.example/token",
                    "oauth2_client_id": "client-id",
                    "oauth2_client_secret": "client-secret",
                }
            ]
        ),
    )

    settings = MCPSettings()

    server = settings.resolve_servers()[0]
    assert server.auth_mode == "auto"
    assert server.oauth2_token_url == "https://idp.example/token"


def test_server_explicit_auto_allows_interactive_oauth_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        SettingsEnv.TIMEBASE_SERVERS,
        json.dumps(
            [
                {
                    "name": "prod",
                    "url": "dxtick://prod:8011",
                    "auth_mode": "auto",
                    "oauth2_client_id": "interactive-client",
                    "oauth2_scope": "openid profile",
                }
            ]
        ),
    )

    settings = MCPSettings()

    server = settings.resolve_servers()[0]
    assert server.auth_mode == "auto"
    assert server.oauth2_client_id == "interactive-client"
    assert server.oauth2_scope == "openid profile"


def test_server_explicit_auto_rejects_ambiguous_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        SettingsEnv.TIMEBASE_SERVERS,
        json.dumps(
            [
                {
                    "name": "prod",
                    "url": "dxtick://prod:8011",
                    "auth_mode": "auto",
                    "username": "u",
                    "password": "p",
                    "oauth2_token_url": "https://idp.example/token",
                    "oauth2_client_id": "client-id",
                    "oauth2_client_secret": "client-secret",
                }
            ]
        ),
    )

    with pytest.raises(ValidationError, match="cannot resolve both"):
        MCPSettings()


def test_server_none_auth_rejects_username(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        SettingsEnv.TIMEBASE_SERVERS,
        json.dumps(
            [
                {
                    "name": "prod",
                    "url": "dxtick://prod:8011",
                    "auth_mode": "none",
                    "username": "u",
                }
            ]
        ),
    )

    with pytest.raises(ValidationError, match="cannot be combined"):
        MCPSettings()


def test_server_oauth2_rejects_reserved_token_params(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        SettingsEnv.TIMEBASE_SERVERS,
        json.dumps(
            [
                {
                    "name": "prod",
                    "url": "dxtick://prod:8011",
                    "auth_mode": "oauth2_client_credentials",
                    "oauth2_token_url": "https://idp.example/token",
                    "oauth2_client_id": "client-id",
                    "oauth2_client_secret": "client-secret",
                    "oauth2_token_params": {"scope": "override"},
                }
            ]
        ),
    )

    with pytest.raises(ValidationError, match="reserved OAuth2 fields"):
        MCPSettings()


def test_servers_conflict_with_flat_connection_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        SettingsEnv.TIMEBASE_SERVERS,
        json.dumps([{"name": "prod", "url": "dxtick://prod:8011"}]),
    )
    monkeypatch.setenv(SettingsEnv.TIMEBASE_USERNAME, "x")
    monkeypatch.setenv(SettingsEnv.TIMEBASE_PASSWORD, "y")

    with pytest.raises(ValidationError, match="cannot be combined"):
        MCPSettings()


def test_servers_load_from_file_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    servers_file = tmp_path / "servers.json"
    servers_file.write_text(
        json.dumps(
            [
                {"name": "prod", "url": "dxtick://prod:8011"},
                {"name": "dev", "url": "dxtick://dev:8011"},
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv(SettingsEnv.TIMEBASE_SERVERS, str(servers_file))

    settings = MCPSettings()
    servers = settings.resolve_servers()

    assert [server.instance_key for server in servers] == ["prod", "dev"]


def test_servers_load_from_indexed_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(SettingsEnv.TIMEBASE_SERVERS, raising=False)
    monkeypatch.setenv(f"{SettingsEnv.TIMEBASE_SERVERS}_0_NAME", "enterprise")
    monkeypatch.setenv(
        f"{SettingsEnv.TIMEBASE_SERVERS}_0_DESCRIPTION", "Enterprise TimeBase"
    )
    monkeypatch.setenv(
        f"{SettingsEnv.TIMEBASE_SERVERS}_0_URL", "dxtick://localhost:8011"
    )
    monkeypatch.setenv(f"{SettingsEnv.TIMEBASE_SERVERS}_1_NAME", "community")
    monkeypatch.setenv(
        f"{SettingsEnv.TIMEBASE_SERVERS}_1_URL", "dxtick://localhost:8012"
    )

    settings = MCPSettings()
    servers = settings.resolve_servers()

    assert [server.instance_key for server in servers] == ["enterprise", "community"]
    assert servers[0].description == "Enterprise TimeBase"


def test_servers_indexed_env_supports_basic_auth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(SettingsEnv.TIMEBASE_SERVERS, raising=False)
    monkeypatch.setenv(f"{SettingsEnv.TIMEBASE_SERVERS}_0_URL", "dxtick://prod:8011")
    monkeypatch.setenv(f"{SettingsEnv.TIMEBASE_SERVERS}_0_USERNAME", "alice")
    monkeypatch.setenv(f"{SettingsEnv.TIMEBASE_SERVERS}_0_PASSWORD", "secret")

    server = MCPSettings().resolve_servers()[0]

    assert server.auth_mode == "basic"
    assert server.username == "alice"
    assert server.password is not None
    assert server.password.get_secret_value() == "secret"


def test_servers_indexed_env_stops_at_first_missing_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(SettingsEnv.TIMEBASE_SERVERS, raising=False)
    monkeypatch.setenv(
        f"{SettingsEnv.TIMEBASE_SERVERS}_0_URL", "dxtick://localhost:8011"
    )
    monkeypatch.setenv(
        f"{SettingsEnv.TIMEBASE_SERVERS}_2_URL", "dxtick://localhost:8013"
    )

    servers = MCPSettings().resolve_servers()

    assert len(servers) == 1
    assert servers[0].url == "dxtick://localhost:8011"


def test_servers_scalar_cannot_be_combined_with_indexed_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        SettingsEnv.TIMEBASE_SERVERS,
        json.dumps([{"name": "prod", "url": "dxtick://prod:8011"}]),
    )
    monkeypatch.setenv(
        f"{SettingsEnv.TIMEBASE_SERVERS}_0_URL", "dxtick://localhost:8011"
    )

    with pytest.raises(ValidationError, match="cannot be combined"):
        MCPSettings()


def test_default_server_built_from_flat_settings() -> None:
    settings = MCPSettings()
    servers = settings.resolve_servers()

    assert len(servers) == 1
    assert servers[0].instance_key == "default"
    assert servers[0].auth_mode == "auto"


def test_url_only_http_transport_still_defaults_to_auto(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(SettingsEnv.MCP_TRANSPORT, "streamable-http")

    settings = MCPSettings()

    assert settings.resolve_servers()[0].auth_mode == "auto"


def test_forward_identity_requires_inbound_auth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(SettingsEnv.TIMEBASE_AUTH_MODE, "forward_identity")

    with pytest.raises(ValidationError, match="forward_identity"):
        MCPSettings()


def test_forward_identity_on_stdio_fails_even_with_audience(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(SettingsEnv.TIMEBASE_AUTH_MODE, "forward_identity")
    monkeypatch.setenv(SettingsEnv.MCP_AUTH_AUDIENCE, "timebase-api")

    with pytest.raises(ValidationError, match="inbound auth"):
        MCPSettings()


def test_forward_identity_valid_on_http_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(SettingsEnv.TIMEBASE_AUTH_MODE, "forward_identity")
    monkeypatch.setenv(SettingsEnv.MCP_TRANSPORT, "streamable-http")
    monkeypatch.setenv(SettingsEnv.MCP_AUTH_PUBLIC_URL, "https://mcp.example.com/mcp")
    monkeypatch.setenv(SettingsEnv.MCP_AUTH_AUDIENCE, "timebase-api")

    settings = MCPSettings()

    assert settings.resolve_servers()[0].auth_mode == "forward_identity"


def test_interactive_mode_allows_url_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(SettingsEnv.TIMEBASE_AUTH_MODE, "interactive")

    settings = MCPSettings()

    assert settings.resolve_servers()[0].auth_mode == "interactive"


def test_interactive_mode_allows_client_id_and_scope_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(SettingsEnv.TIMEBASE_AUTH_MODE, "interactive")
    monkeypatch.setenv(SettingsEnv.TIMEBASE_OAUTH2_CLIENT_ID, "interactive-client")
    monkeypatch.setenv(SettingsEnv.TIMEBASE_OAUTH2_SCOPE, "openid profile")

    settings = MCPSettings()
    server = settings.resolve_servers()[0]

    assert server.auth_mode == "interactive"
    assert server.oauth2_client_id == "interactive-client"
    assert server.oauth2_scope == "openid profile"


@pytest.mark.parametrize(
    ("env_var", "value"),
    [
        (SettingsEnv.TIMEBASE_OAUTH2_TOKEN_URL, "https://idp.example/token"),
        (SettingsEnv.TIMEBASE_OAUTH2_CLIENT_SECRET, "secret"),
        (SettingsEnv.TIMEBASE_OAUTH2_TOKEN_PARAMS, '{"audience": "api"}'),
    ],
)
def test_interactive_mode_rejects_service_oauth_settings(
    monkeypatch: pytest.MonkeyPatch,
    env_var: str,
    value: str,
) -> None:
    monkeypatch.setenv(SettingsEnv.TIMEBASE_AUTH_MODE, "interactive")
    monkeypatch.setenv(env_var, value)

    with pytest.raises(ValidationError, match="interactive"):
        MCPSettings()


@pytest.mark.parametrize(
    "host",
    ["0.0.0.0", "127.0.0.1"],
)
def test_interactive_mode_rejected_on_http_transport(
    monkeypatch: pytest.MonkeyPatch,
    host: str,
) -> None:
    monkeypatch.setenv(SettingsEnv.TIMEBASE_AUTH_MODE, "interactive")
    monkeypatch.setenv(SettingsEnv.MCP_TRANSPORT, "streamable-http")
    monkeypatch.setenv(SettingsEnv.MCP_HOST, host)

    with pytest.raises(ValidationError, match="stdio transport"):
        MCPSettings()


@pytest.mark.parametrize("mode", ["none", "forward_identity", "interactive"])
def test_explicit_non_credential_auth_modes_reject_username(
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    monkeypatch.setenv(SettingsEnv.TIMEBASE_AUTH_MODE, mode)
    monkeypatch.setenv(SettingsEnv.TIMEBASE_USERNAME, "u")

    if mode == "forward_identity":
        monkeypatch.setenv(SettingsEnv.MCP_AUTH_AUDIENCE, "timebase-api")
        monkeypatch.setenv(
            SettingsEnv.MCP_AUTH_PUBLIC_URL, "https://mcp.example.com/mcp"
        )
        monkeypatch.setenv(SettingsEnv.MCP_TRANSPORT, "streamable-http")

    with pytest.raises(ValidationError, match="cannot be combined|both be set"):
        MCPSettings()


def test_explicit_auto_allows_basic_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(SettingsEnv.TIMEBASE_AUTH_MODE, "auto")
    monkeypatch.setenv(SettingsEnv.TIMEBASE_USERNAME, "u")
    monkeypatch.setenv(SettingsEnv.TIMEBASE_PASSWORD, "p")

    settings = MCPSettings()

    server = settings.resolve_servers()[0]
    assert server.auth_mode == "auto"
    assert server.username == "u"
    assert server.password is not None
    assert server.password.get_secret_value() == "p"


def test_explicit_auto_allows_oauth2_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(SettingsEnv.TIMEBASE_AUTH_MODE, "auto")
    monkeypatch.setenv(
        SettingsEnv.TIMEBASE_OAUTH2_TOKEN_URL, "https://idp.example/token"
    )
    monkeypatch.setenv(SettingsEnv.TIMEBASE_OAUTH2_CLIENT_ID, "client-id")
    monkeypatch.setenv(SettingsEnv.TIMEBASE_OAUTH2_CLIENT_SECRET, "client-secret")

    settings = MCPSettings()

    server = settings.resolve_servers()[0]
    assert server.auth_mode == "auto"
    assert server.oauth2_token_url == "https://idp.example/token"


def test_explicit_auto_allows_interactive_oauth_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(SettingsEnv.TIMEBASE_AUTH_MODE, "auto")
    monkeypatch.setenv(SettingsEnv.TIMEBASE_OAUTH2_CLIENT_ID, "interactive-client")
    monkeypatch.setenv(SettingsEnv.TIMEBASE_OAUTH2_SCOPE, "openid profile")

    settings = MCPSettings()
    server = settings.resolve_servers()[0]

    assert server.auth_mode == "auto"
    assert server.oauth2_client_id == "interactive-client"
    assert server.oauth2_scope == "openid profile"


def test_auth_mode_none_rejects_password(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(SettingsEnv.TIMEBASE_AUTH_MODE, "none")
    monkeypatch.setenv(SettingsEnv.TIMEBASE_USERNAME, "u")
    monkeypatch.setenv(SettingsEnv.TIMEBASE_PASSWORD, "p")

    with pytest.raises(ValidationError, match="cannot be combined"):
        MCPSettings()


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


def _make_rsa_verifier(
    *,
    issuer: str = "https://idp.example",
    audience: str | None = None,
    required_scopes: list[str] | None = None,
) -> tuple[JwksTokenVerifier, rsa.RSAPrivateKey]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    verifier = JwksTokenVerifier(
        jwks_uri="https://idp.example/jwks",
        issuer=issuer,
        audience=audience,
        required_scopes=required_scopes,
    )
    verifier._jwks_client = types.SimpleNamespace(  # type: ignore[attr-defined]
        get_signing_key_from_jwt=lambda _token: types.SimpleNamespace(
            key=private_key.public_key()
        )
    )
    return verifier, private_key


@pytest.mark.anyio
async def test_jwks_verifier_accepts_valid_token() -> None:
    verifier, private_key = _make_rsa_verifier()
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
    verifier, private_key = _make_rsa_verifier(issuer="https://idp.example")
    token = jwt.encode(
        {"iss": "https://evil.example", "sub": "user-1"},
        private_key,
        algorithm="RS256",
    )

    assert await verifier.verify_token(token) is None


@pytest.mark.anyio
async def test_jwks_verifier_enforces_required_scopes() -> None:
    verifier, private_key = _make_rsa_verifier(required_scopes=["timebase.write"])
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


def test_build_inbound_auth_disabled_returns_none() -> None:
    assert build_inbound_auth(MCPSettings()) is None


def test_inbound_http_auth_disabled_without_audience_or_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(SettingsEnv.MCP_TRANSPORT, "streamable-http")

    settings = MCPSettings()

    assert settings.inbound_auth_enabled is False
    assert build_inbound_auth(settings) is None


def test_remote_jwt_auth_requires_public_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(SettingsEnv.MCP_TRANSPORT, "streamable-http")
    monkeypatch.setenv(SettingsEnv.MCP_HOST, "0.0.0.0")
    monkeypatch.setenv(SettingsEnv.MCP_AUTH_AUDIENCE, "timebase-api")

    with pytest.raises(ValidationError, match="MCP_AUTH_PUBLIC_URL"):
        MCPSettings()


def test_remote_jwt_auth_requires_https_public_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(SettingsEnv.MCP_TRANSPORT, "streamable-http")
    monkeypatch.setenv(SettingsEnv.MCP_HOST, "0.0.0.0")
    monkeypatch.setenv(SettingsEnv.MCP_AUTH_AUDIENCE, "timebase-api")
    monkeypatch.setenv(SettingsEnv.MCP_AUTH_PUBLIC_URL, "http://mcp.example.com/mcp")

    with pytest.raises(ValidationError, match="MCP_AUTH_PUBLIC_URL"):
        MCPSettings()


def test_remote_jwt_auth_accepts_https_public_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(SettingsEnv.MCP_TRANSPORT, "streamable-http")
    monkeypatch.setenv(SettingsEnv.MCP_HOST, "0.0.0.0")
    monkeypatch.setenv(SettingsEnv.MCP_AUTH_AUDIENCE, "timebase-api")
    monkeypatch.setenv(SettingsEnv.MCP_AUTH_PUBLIC_URL, "https://mcp.example.com/mcp")

    settings = MCPSettings()

    assert settings.inbound_auth_mode == "jwt"
    assert settings.auth_public_url == "https://mcp.example.com/mcp"


@pytest.mark.anyio
async def test_build_inbound_auth_with_api_keys_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    record, raw_key = keystore.build_record(name="alice", scopes=["timebase.read"])
    keys_file = tmp_path / "keys.json"
    keystore.write_store(keys_file, [record])

    monkeypatch.setenv(SettingsEnv.MCP_TRANSPORT, "streamable-http")
    monkeypatch.setenv(SettingsEnv.MCP_AUTH_API_KEYS_FILE, str(keys_file))

    inbound = build_inbound_auth(MCPSettings())

    assert inbound is not None
    assert inbound.auth_settings.resource_server_url is None
    assert await inbound.token_verifier.verify_token(raw_key) is not None
    assert await inbound.token_verifier.verify_token("tbk_unknown") is None


def test_derive_http_base_url() -> None:
    assert derive_http_base_url("dxtick://host:8011") == "http://host:8011"
    assert derive_http_base_url("dxctick://h1:8010|h2:8011") == "http://h1:8010"
    assert derive_http_base_url("not a url") is None


def test_derive_http_base_urls_prefers_https_for_ssl_termination(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DXAPI_SSL_TERMINATION", "true")

    assert derive_http_base_urls("dxtick://tb.example.com:8011") == (
        "https://tb.example.com:8011",
        "http://tb.example.com:8011",
    )


def test_resolve_interactive_redirect_uri_defaults_to_mcp_host_port() -> None:
    assert (
        resolve_interactive_redirect_uri(
            host="127.0.0.1",
            port=8000,
        )
        == "http://127.0.0.1:8000/"
    )


def test_resolve_interactive_redirect_uri_preserves_localhost() -> None:
    assert (
        resolve_interactive_redirect_uri(
            host="localhost",
            port=4276,
        )
        == "http://localhost:4276/"
    )


def test_resolve_interactive_redirect_uri_normalizes_wildcard_host() -> None:
    assert (
        resolve_interactive_redirect_uri(
            host="0.0.0.0",
            port=8765,
        )
        == "http://127.0.0.1:8765/"
    )


def test_settings_resolved_interactive_redirect_uri(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(SettingsEnv.MCP_HOST, "0.0.0.0")
    monkeypatch.setenv(SettingsEnv.MCP_PORT, "8123")

    settings = MCPSettings()

    assert settings.resolved_interactive_redirect_uri == "http://127.0.0.1:8123/"


def test_settings_resolved_interactive_redirect_uri_preserves_localhost(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(SettingsEnv.MCP_HOST, "localhost")
    monkeypatch.setenv(SettingsEnv.MCP_PORT, "4276")

    settings = MCPSettings()

    assert settings.resolved_interactive_redirect_uri == "http://localhost:4276/"


def test_settings_resolved_interactive_redirect_uri_is_none_for_http(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(SettingsEnv.MCP_TRANSPORT, "streamable-http")

    settings = MCPSettings()

    assert settings.resolved_interactive_redirect_uri is None


def test_derive_http_base_urls_prefers_https_for_ssl_scheme() -> None:
    assert derive_http_base_urls("dstick://tb.example.com:8011") == (
        "https://tb.example.com:8011",
        "http://tb.example.com:8011",
    )


class _DiscoveryResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return

    def json(self) -> dict:
        return self._payload


def _timebase_oauthinfo_payload() -> dict:
    return {
        "issuer": "https://login.microsoftonline.com/tenant/v2.0",
        "clientid": [
            {"app": "timebase.client.service", "name": "service-client"},
            {"app": "timebase.client.application", "name": "application-client"},
        ],
        "scope": "api://api-id/app openid profile offline_access",
        "scopes": [
            {
                "app": "timebase.client.application",
                "scope": "api://api-id/app openid profile offline_access",
            },
            {"app": "timebase.client.service", "scope": "api://api-id/.default"},
        ],
    }


def test_fetch_oauthinfo_parses_timebase_application_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_get(url: str, *, timeout: float, verify: bool) -> _DiscoveryResponse:
        assert url == "https://tb.example.com:8011/tb/oauthinfo"
        assert timeout > 0
        assert verify is True
        return _DiscoveryResponse(_timebase_oauthinfo_payload())

    monkeypatch.setattr("timebase_mcp.auth.discovery.httpx.get", fake_get)

    info = fetch_oauthinfo("https://tb.example.com:8011")

    assert info.issuer == "https://login.microsoftonline.com/tenant/v2.0"
    assert info.client_id == "application-client"
    assert info.scope == "api://api-id/app openid profile offline_access"
    assert info.discovery_base_url == "https://tb.example.com:8011"


def test_fetch_oauthinfo_uses_single_clientid_without_app(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_get(_url: str, *, timeout: float, verify: bool) -> _DiscoveryResponse:
        return _DiscoveryResponse(
            {
                "issuer": "https://idp.example",
                "clientid": [{"name": "single-client"}],
                "scopes": [{"scope": "openid profile"}],
            }
        )

    monkeypatch.setattr("timebase_mcp.auth.discovery.httpx.get", fake_get)

    info = fetch_oauthinfo("https://tb.example.com:8011")

    assert info.client_id == "single-client"
    assert info.scope == "openid profile"


def test_fetch_oauthinfo_allows_empty_payload_when_auth_not_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _EmptyResponse:
        headers = {"content-type": "text/plain"}
        content = b""

        def raise_for_status(self) -> None:
            return

        def json(self) -> dict:
            raise ValueError("bad json")

    monkeypatch.setattr(
        "timebase_mcp.auth.discovery.httpx.get",
        lambda _url, *, timeout, verify: _EmptyResponse(),
    )

    info = fetch_oauthinfo("http://tb.example.com:8011")

    assert info.issuer is None
    assert info.client_id is None
    assert info.scope is None


def test_fetch_oauthinfo_raises_configuration_error_for_non_empty_invalid_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _InvalidJsonResponse:
        headers = {"content-type": "text/plain"}
        content = b"not-json"

        def raise_for_status(self) -> None:
            return

        def json(self) -> dict:
            raise ValueError("bad json")

    monkeypatch.setattr(
        "timebase_mcp.auth.discovery.httpx.get",
        lambda _url, *, timeout, verify: _InvalidJsonResponse(),
    )

    with pytest.raises(ConfigurationError, match="Expected JSON response"):
        fetch_oauthinfo("http://tb.example.com:8011")


def test_resolve_interactive_endpoints_tries_https_candidate_and_trusts_all(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv("DXAPI_SSL_TERMINATION", "true")
    monkeypatch.setenv("DXAPI_SSL_TRUST_ALL", "true")
    monkeypatch.setattr(discovery_module, "_trust_all_warning_emitted", False)
    calls: list[tuple[str, bool]] = []

    def fake_get(url: str, *, timeout: float, verify: bool) -> _DiscoveryResponse:
        calls.append((url, verify))
        if url == "https://tb.example.com:8011/tb/oauthinfo":
            return _DiscoveryResponse(_timebase_oauthinfo_payload())
        if (
            url
            == "https://login.microsoftonline.com/tenant/v2.0/.well-known/openid-configuration"
        ):
            return _DiscoveryResponse(
                {
                    "authorization_endpoint": "https://login.example/auth",
                    "token_endpoint": "https://login.example/token",
                    "jwks_uri": "https://login.example/jwks",
                }
            )
        raise AssertionError(f"unexpected URL: {url}")

    monkeypatch.setattr("timebase_mcp.auth.discovery.httpx.get", fake_get)

    with caplog.at_level(logging.WARNING):
        endpoints = resolve_interactive_endpoints(
            discovery_base_url=derive_http_base_urls("dxtick://tb.example.com:8011"),
            issuer_override=None,
            client_id_override=None,
            scope_override=None,
        )

    assert endpoints.authorization_endpoint == "https://login.example/auth"
    assert endpoints.token_endpoint == "https://login.example/token"
    assert endpoints.client_id == "application-client"
    assert endpoints.scope == "api://api-id/app openid profile offline_access"
    assert endpoints.discovery_base_url == "https://tb.example.com:8011"
    assert calls == [
        ("https://tb.example.com:8011/tb/oauthinfo", False),
        (
            "https://login.microsoftonline.com/tenant/v2.0/.well-known/openid-configuration",
            False,
        ),
    ]
    assert caplog.text.count("DXAPI_SSL_TRUST_ALL=true disables TLS") == 1


def test_trust_all_warning_emits_once_for_multiple_discovery_calls(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv("DXAPI_SSL_TRUST_ALL", "true")
    monkeypatch.setattr(discovery_module, "_trust_all_warning_emitted", False)

    def fake_get(_url: str, *, timeout: float, verify: bool) -> _DiscoveryResponse:
        assert verify is False
        return _DiscoveryResponse(_timebase_oauthinfo_payload())

    monkeypatch.setattr("timebase_mcp.auth.discovery.httpx.get", fake_get)

    with caplog.at_level(logging.WARNING):
        fetch_oauthinfo("https://tb.example.com:8011")
        fetch_oauthinfo("https://tb.example.com:8011")

    assert caplog.text.count("DXAPI_SSL_TRUST_ALL=true disables TLS") == 1


def test_trust_all_warning_not_emitted_when_verification_enabled(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.delenv("DXAPI_SSL_TRUST_ALL", raising=False)
    monkeypatch.setattr(discovery_module, "_trust_all_warning_emitted", False)

    def fake_get(_url: str, *, timeout: float, verify: bool) -> _DiscoveryResponse:
        assert verify is True
        return _DiscoveryResponse(_timebase_oauthinfo_payload())

    monkeypatch.setattr("timebase_mcp.auth.discovery.httpx.get", fake_get)

    with caplog.at_level(logging.WARNING):
        fetch_oauthinfo("https://tb.example.com:8011")

    assert "DXAPI_SSL_TRUST_ALL=true disables TLS" not in caplog.text


class _StubClient:
    def __init__(self, *, key: str, read_only: bool) -> None:
        self.key = key
        self.read_only = read_only

    def close(self) -> None:
        return

    def interrupt(self) -> None:
        return


def _forward_identity_settings() -> MCPSettings:
    return MCPSettings(
        transport="streamable-http",
        auth_audience="timebase-api",
        auth_public_url="https://mcp.example.com/mcp",
        tb_auth_mode="forward_identity",
    )


@pytest.mark.anyio
async def test_forward_identity_uses_per_principal_pool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list = []

    def build_client(instance, *, read_only: bool = False, config=None):
        captured.append(config)
        return _StubClient(key=instance.key, read_only=read_only)

    monkeypatch.setattr(
        "timebase_mcp.clients.factory.create_timebase_client", build_client
    )

    runtime = build_runtime(_forward_identity_settings())
    instance = runtime.default_instance

    access = AccessToken(
        token="caller-jwt",
        client_id="cid",
        scopes=[],
        subject="user-1",
        claims={"preferred_username": "alice"},
    )
    reset = auth_context_var.set(AuthenticatedUser(access))
    try:
        await run_with_runtime(runtime, lambda client: id(client))
    finally:
        auth_context_var.reset(reset)

    assert "user-1" in instance._principal_pools
    assert captured and captured[0].access_token == "caller-jwt"
    assert captured[0].access_token_username == "alice"

    await runtime.aclose()


@pytest.mark.anyio
async def test_forward_identity_rotates_pool_when_principal_token_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list = []
    created_clients: list[_StubClient] = []

    def build_client(instance, *, read_only: bool = False, config=None):
        captured.append(config)
        client = _StubClient(key=instance.key, read_only=read_only)
        created_clients.append(client)
        return client

    monkeypatch.setattr(
        "timebase_mcp.clients.factory.create_timebase_client", build_client
    )

    runtime = build_runtime(_forward_identity_settings())

    def set_principal(token: str):
        access = AccessToken(
            token=token,
            client_id="cid",
            scopes=[],
            subject="user-1",
            claims={"preferred_username": "alice"},
        )
        return auth_context_var.set(AuthenticatedUser(access))

    reset = set_principal("caller-jwt-1")
    try:
        first_client_id = await run_with_runtime(runtime, lambda client: id(client))
    finally:
        auth_context_var.reset(reset)

    reset = set_principal("caller-jwt-2")
    try:
        second_client_id = await run_with_runtime(runtime, lambda client: id(client))
    finally:
        auth_context_var.reset(reset)

    assert first_client_id != second_client_id
    assert [config.access_token for config in captured] == [
        "caller-jwt-1",
        "caller-jwt-2",
    ]
    assert len(created_clients) == 2

    await runtime.aclose()


@pytest.mark.anyio
async def test_forward_identity_without_principal_raises() -> None:
    runtime = build_runtime(_forward_identity_settings())

    with pytest.raises(TimeBaseOperationStateError, match="not authenticated"):
        await run_with_runtime(runtime, lambda client: id(client))

    await runtime.aclose()


def _interactive_provider(**kwargs) -> InteractiveOAuthProvider:
    provider = InteractiveOAuthProvider(
        discovery_base_url=None,
        redirect_uri="http://127.0.0.1:8000/",
        **kwargs,
    )
    provider._endpoints = InteractiveEndpoints(
        authorization_endpoint="https://idp.example/auth",
        token_endpoint="https://idp.example/token",
        client_id="tb-app",
        scope="openid",
    )
    return provider


def test_interactive_provider_refreshes_and_caches() -> None:
    provider = _interactive_provider()
    provider._refresh_token = "refresh-1"

    calls: list[dict] = []

    def stub_post(_url: str, data: dict):
        calls.append(data)
        from timebase_mcp.auth.oauth2 import parse_token_response

        return parse_token_response(
            {
                "access_token": "access-1",
                "refresh_token": "refresh-2",
                "expires_in": 3600,
            },
            monotonic=provider._monotonic,
            access_token_error="OAuth token response did not include an access_token.",
        )

    provider._post_token = stub_post  # type: ignore[assignment]

    assert provider.get_access_token() == "access-1"
    assert calls[0]["grant_type"] == "refresh_token"

    assert provider.get_access_token() == "access-1"
    assert len(calls) == 1


def test_interactive_provider_posts_token_form_with_content_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _interactive_provider()
    captured: dict[str, object] = {}

    class _Response:
        text = json.dumps({"access_token": "access-1", "expires_in": 120})

        def raise_for_status(self) -> None:
            return

    def fake_post(url: str, *, data: dict, headers: dict, timeout: float):
        captured["url"] = url
        captured["data"] = data
        captured["headers"] = headers
        captured["timeout"] = timeout
        return _Response()

    monkeypatch.setattr("timebase_mcp.auth.interactive.httpx.post", fake_post)

    token_response = provider._post_token(
        "https://idp.example/token",
        {"grant_type": "authorization_code", "code": "code-1"},
    )

    assert token_response.access_token == "access-1"
    assert captured == {
        "url": "https://idp.example/token",
        "data": {"grant_type": "authorization_code", "code": "code-1"},
        "headers": {
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        "timeout": 30,
    }


def test_interactive_provider_requires_redirect_uri_on_login() -> None:
    provider = InteractiveOAuthProvider(discovery_base_url=None)
    provider._endpoints = InteractiveEndpoints(
        authorization_endpoint="https://idp.example/auth",
        token_endpoint="https://idp.example/token",
        client_id="tb-app",
        scope="openid",
    )

    with pytest.raises(ConfigurationError, match="redirect URI is not configured"):
        provider._login()


def test_interactive_provider_token_expiry() -> None:
    clock = {"now": 1000.0}
    provider = InteractiveOAuthProvider(
        discovery_base_url=None,
        redirect_uri="http://127.0.0.1:8000/",
        monotonic=lambda: clock["now"],
    )

    provider._store_token({"access_token": "a", "expires_in": 10})
    assert provider._token_expired() is True

    provider._store_token({"access_token": "a", "expires_in": 3600})
    assert provider._token_expired() is False

    clock["now"] = 1000.0 + 3600
    assert provider._token_expired() is True

    provider._store_token({"access_token": "a"})
    assert provider._token_expired() is False


def _patch_auto_client_creation(monkeypatch: pytest.MonkeyPatch):
    captured_configs: list[TimeBaseInstanceConfig] = []

    class _AutoClient(_StubClient):
        def __init__(self, config: TimeBaseInstanceConfig) -> None:
            super().__init__(key="default", read_only=False)
            self.config = config

        def set_token_provider(self, _provider: object) -> None:
            return

        def open(self) -> None:
            return

    def fake_create_client(
        config: TimeBaseInstanceConfig,
        _edition: str,
        *,
        read_only: bool,
    ) -> _AutoClient:
        captured_configs.append(config)
        return _AutoClient(config)

    monkeypatch.setattr(
        "timebase_mcp.clients.factory._create_client_for_edition",
        fake_create_client,
    )
    monkeypatch.setattr(
        "timebase_mcp.clients.factory._available_editions",
        lambda _statuses=None: ("community",),
    )
    return captured_configs


def _advertise_oauth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "timebase_mcp.clients.factory.resolve_interactive_endpoints",
        lambda **_kwargs: InteractiveEndpoints(
            authorization_endpoint="https://login.example/auth",
            token_endpoint="https://login.example/token",
            client_id="application-client",
            scope="openid",
            discovery_base_url="https://tb.example.com:8011",
        ),
    )


def test_auto_auth_switches_to_interactive_and_sets_ssl_termination(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DXAPI_SSL_TERMINATION", raising=False)
    monkeypatch.setenv(SettingsEnv.TIMEBASE_URL, "dxtick://tb.example.com:8011")
    runtime = build_runtime(MCPSettings())
    captured_configs = _patch_auto_client_creation(monkeypatch)
    _advertise_oauth(monkeypatch)
    monkeypatch.setattr(
        "timebase_mcp.instance.TimeBaseInstanceRuntime.get_interactive_provider",
        lambda _instance: object(),
    )

    create_timebase_client(runtime.default_instance)

    assert captured_configs[0].auth_mode == "interactive"
    assert captured_configs[0].http_base_url == "https://tb.example.com:8011"
    assert runtime.default_instance.config.auth_mode == "interactive"
    assert os.environ["DXAPI_SSL_TERMINATION"] == "true"


def test_auto_auth_passes_interactive_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DXAPI_SSL_TERMINATION", raising=False)
    monkeypatch.setenv(SettingsEnv.TIMEBASE_URL, "dxtick://tb.example.com:8011")
    monkeypatch.setenv(SettingsEnv.TIMEBASE_OAUTH2_CLIENT_ID, "interactive-client")
    monkeypatch.setenv(SettingsEnv.TIMEBASE_OAUTH2_SCOPE, "openid profile")
    runtime = build_runtime(MCPSettings())
    captured_configs = _patch_auto_client_creation(monkeypatch)
    _advertise_oauth(monkeypatch)
    monkeypatch.setattr(
        "timebase_mcp.instance.TimeBaseInstanceRuntime.get_interactive_provider",
        lambda _instance: object(),
    )

    create_timebase_client(runtime.default_instance)

    assert captured_configs[0].auth_mode == "interactive"
    assert captured_configs[0].tb_oauth2_client_id == "interactive-client"
    assert captured_configs[0].tb_oauth2_scope == "openid profile"


def test_auto_auth_switches_to_forward_identity_for_remote_inbound_auth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(SettingsEnv.TIMEBASE_URL, "dxtick://tb.example.com:8011")
    runtime = build_runtime(_forward_identity_settings())
    captured_configs = _patch_auto_client_creation(monkeypatch)
    _advertise_oauth(monkeypatch)

    create_timebase_client(runtime.default_instance)

    assert captured_configs[0].auth_mode == "forward_identity"
    assert runtime.default_instance.config.auth_mode == "forward_identity"


def test_auto_auth_rejects_api_key_inbound_forwarding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(SettingsEnv.TIMEBASE_URL, "dxtick://tb.example.com:8011")
    monkeypatch.setenv(SettingsEnv.MCP_TRANSPORT, "streamable-http")
    monkeypatch.setenv(SettingsEnv.MCP_HOST, "0.0.0.0")
    monkeypatch.setenv(SettingsEnv.MCP_AUTH_API_KEYS_FILE, "/var/run/keys.json")
    runtime = build_runtime(MCPSettings())
    _patch_auto_client_creation(monkeypatch)
    _advertise_oauth(monkeypatch)

    with pytest.raises(ConfigurationError, match="API-key callers cannot be forwarded"):
        create_timebase_client(runtime.default_instance)

    assert runtime.default_instance.config.auth_mode == "auto"


def test_auto_auth_rejects_remote_interactive_without_forwardable_jwt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(SettingsEnv.TIMEBASE_URL, "dxtick://tb.example.com:8011")
    monkeypatch.setenv(SettingsEnv.MCP_TRANSPORT, "streamable-http")
    monkeypatch.setenv(SettingsEnv.MCP_HOST, "0.0.0.0")
    runtime = build_runtime(MCPSettings())
    _patch_auto_client_creation(monkeypatch)
    _advertise_oauth(monkeypatch)

    with pytest.raises(ConfigurationError, match="interactive login is only supported"):
        create_timebase_client(runtime.default_instance)

    assert runtime.default_instance.config.auth_mode == "auto"


def test_auto_auth_rejects_interactive_on_loopback_http(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(SettingsEnv.TIMEBASE_URL, "dxtick://tb.example.com:8011")
    monkeypatch.setenv(SettingsEnv.MCP_TRANSPORT, "streamable-http")
    runtime = build_runtime(MCPSettings())
    _patch_auto_client_creation(monkeypatch)
    _advertise_oauth(monkeypatch)

    with pytest.raises(ConfigurationError, match="interactive login is only supported"):
        create_timebase_client(runtime.default_instance)

    assert runtime.default_instance.config.auth_mode == "auto"


def test_auto_auth_switches_to_basic_when_credentials_are_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(SettingsEnv.TIMEBASE_AUTH_MODE, "auto")
    monkeypatch.setenv(SettingsEnv.TIMEBASE_USERNAME, "u")
    monkeypatch.setenv(SettingsEnv.TIMEBASE_PASSWORD, "p")
    runtime = build_runtime(MCPSettings())
    captured_configs = _patch_auto_client_creation(monkeypatch)
    _advertise_oauth(monkeypatch)

    create_timebase_client(runtime.default_instance)

    assert captured_configs[0].auth_mode == "basic"
    assert captured_configs[0].tb_username == "u"
    assert runtime.default_instance.config.auth_mode == "basic"


def test_auto_auth_switches_to_oauth2_when_client_credentials_are_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(SettingsEnv.TIMEBASE_AUTH_MODE, "auto")
    monkeypatch.setenv(
        SettingsEnv.TIMEBASE_OAUTH2_TOKEN_URL, "https://idp.example/token"
    )
    monkeypatch.setenv(SettingsEnv.TIMEBASE_OAUTH2_CLIENT_ID, "client-id")
    monkeypatch.setenv(SettingsEnv.TIMEBASE_OAUTH2_CLIENT_SECRET, "client-secret")
    runtime = build_runtime(MCPSettings())
    captured_configs = _patch_auto_client_creation(monkeypatch)
    _advertise_oauth(monkeypatch)

    create_timebase_client(runtime.default_instance)

    assert captured_configs[0].auth_mode == "oauth2_client_credentials"
    assert captured_configs[0].oauth2_config is not None
    assert runtime.default_instance.config.auth_mode == "oauth2_client_credentials"


def test_auto_auth_switches_to_none_when_discovery_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(SettingsEnv.TIMEBASE_URL, "dxtick://tb.example.com:8011")
    runtime = build_runtime(MCPSettings())
    captured_configs = _patch_auto_client_creation(monkeypatch)

    def fail_discovery(**_kwargs):
        from timebase_mcp.errors import ConfigurationError

        raise ConfigurationError("not advertised")

    monkeypatch.setattr(
        "timebase_mcp.clients.factory.resolve_interactive_endpoints",
        fail_discovery,
    )

    create_timebase_client(runtime.default_instance)

    assert captured_configs[0].auth_mode == "none"
    assert captured_configs[0].auto_auth_error == "not advertised"
    assert runtime.default_instance.config.auth_mode == "none"


def test_enterprise_auto_auth_hint_includes_discovery_failure() -> None:
    config = TimeBaseInstanceConfig(
        tb_url="dxtick://tb.example.com:8011",
        auth_mode="auto",
        auto_auth_error="Failed to fetch TimeBase OAuth metadata.",
    )
    client = EnterpriseTimeBaseClient(config)

    hint = client._connection_error_hint(
        Exception("Handshake failed: Wrong username or password")
    )

    assert "TIMEBASE_AUTH_MODE=interactive" in hint
    assert "OAuth auto-discovery failed earlier" in hint


def test_inbound_auth_disabled_for_stdio_default() -> None:
    settings = MCPSettings()  # transport defaults to stdio

    assert settings.inbound_auth_enabled is False


def test_inbound_auth_disabled_for_loopback_http(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(SettingsEnv.MCP_TRANSPORT, "streamable-http")
    # MCP_HOST defaults to 127.0.0.1

    settings = MCPSettings()

    assert settings.inbound_auth_enabled is False


def test_inbound_auth_enabled_for_nonloopback_http(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(SettingsEnv.MCP_TRANSPORT, "streamable-http")
    monkeypatch.setenv(SettingsEnv.MCP_HOST, "0.0.0.0")
    # Provide a keys file path so the validator doesn't require MCP_AUTH_AUDIENCE
    monkeypatch.setenv(SettingsEnv.MCP_AUTH_API_KEYS_FILE, "/var/run/keys.json")

    settings = MCPSettings()

    assert settings.inbound_auth_enabled is True


def test_inbound_auth_disabled_without_auth_config_on_remote(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(SettingsEnv.MCP_TRANSPORT, "streamable-http")
    monkeypatch.setenv(SettingsEnv.MCP_HOST, "0.0.0.0")

    settings = MCPSettings()

    assert settings.inbound_auth_enabled is False
    assert build_inbound_auth(settings) is None


def test_inbound_auth_enabled_on_loopback_with_audience(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(SettingsEnv.MCP_TRANSPORT, "streamable-http")
    monkeypatch.setenv(SettingsEnv.MCP_AUTH_AUDIENCE, "timebase-api")

    settings = MCPSettings()

    assert settings.inbound_auth_enabled is True
    assert settings.inbound_auth_mode == "jwt"


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


def test_forward_identity_rejects_api_keys_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(SettingsEnv.TIMEBASE_AUTH_MODE, "forward_identity")
    monkeypatch.setenv(SettingsEnv.MCP_TRANSPORT, "streamable-http")
    monkeypatch.setenv(SettingsEnv.MCP_AUTH_AUDIENCE, "timebase-api")
    monkeypatch.setenv(SettingsEnv.MCP_AUTH_API_KEYS_FILE, "/var/run/keys.json")

    with pytest.raises(ValidationError, match="forward_identity"):
        MCPSettings()
