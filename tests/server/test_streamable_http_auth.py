from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import anyio.to_thread
import httpx2
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm
from mcp.client.auth import OAuthClientProvider
from mcp.server.auth.middleware.bearer_auth import (
    BearerAuthBackend,
    RequireAuthMiddleware,
)
from mcp.server.auth.provider import TokenVerifier
from mcp.server.transport_security import TransportSecuritySettings
from mcp.shared.auth import (
    AuthorizationCodeResult,
    OAuthClientInformationFull,
    OAuthClientMetadata,
    OAuthToken,
)
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.authentication import AuthenticationMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route
from starlette.testclient import TestClient
from typing_extensions import override

from tests.auth.helpers import make_rsa_verifier
from tests.stubs import StubTimeBaseClient
from tests.support.mcp_http import (
    build_client_meta,
    build_modern_headers,
    parse_jsonrpc_response,
)
from timebase_mcp.auth import keystore
from timebase_mcp.auth.keystore import KeyStore
from timebase_mcp.auth.outbound import (
    TimeBaseCredentials,
    resolve_timebase_credentials,
)
from timebase_mcp.auth.token_verifier import ApiKeyStoreVerifier
from timebase_mcp.config.settings import MCPSettings
from timebase_mcp.models.core import StreamInfo
from timebase_mcp.runtime.instance import TimeBaseInstanceRuntime
from timebase_mcp.server import create_server

_RESOURCE = "https://mcp.example.com/mcp"
_SCOPE = f"{_RESOURCE}/mcp.access"
_ISSUER = "https://login.example.com/tenant/v2.0"
_AUDIENCE = "shared-api-application-id"
_CLIENT_META = build_client_meta(client_name="shared-resource-auth-test")


def _single_worker_loop() -> asyncio.AbstractEventLoop:
    loop = asyncio.new_event_loop()
    loop.set_default_executor(ThreadPoolExecutor(max_workers=1))
    return loop


@pytest.mark.parametrize("auth_mode", ["api_key", "jwt"])
@pytest.mark.parametrize(
    "anyio_backend",
    [("asyncio", {"loop_factory": _single_worker_loop})],
    ids=["single-worker"],
)
@pytest.mark.anyio
async def test_http_auth_works_when_worker_pools_are_saturated(
    tmp_path: Path, anyio_backend: object, auth_mode: str
) -> None:
    verifier: TokenVerifier
    if auth_mode == "jwt":
        verifier, signing_key = make_rsa_verifier(required_scopes=["read"])
        token = jwt.encode(
            {"iss": "https://idp.example", "scope": "read", "exp": int(time.time()) + 300},
            signing_key,
            algorithm="RS256",
        )
    else:
        record, token = keystore.build_record(name="alice", scopes=["read"])
        keys_file = tmp_path / "keys.json"
        keystore.write_store(keys_file, [record])
        verifier = ApiKeyStoreVerifier(KeyStore(keys_file))

    async def accepted(_request: Request) -> Response:
        return Response(status_code=202)

    app = Starlette(
        routes=[Route("/mcp", accepted, methods=["POST"])],
        middleware=[
            Middleware(AuthenticationMiddleware, backend=BearerAuthBackend(verifier)),
            Middleware(RequireAuthMiddleware, required_scopes=["read"]),
        ],
    )
    loop = asyncio.get_running_loop()
    release = threading.Event()
    native_started, anyio_started = asyncio.Event(), asyncio.Event()

    def occupy_worker(started: asyncio.Event) -> None:
        loop.call_soon_threadsafe(started.set)
        assert release.wait(5), "Worker was not released during cleanup"

    limiter = anyio.to_thread.current_default_thread_limiter()
    previous_tokens = limiter.total_tokens
    limiter.total_tokens = 1
    native_worker = loop.run_in_executor(None, occupy_worker, native_started)
    anyio_worker = asyncio.create_task(
        anyio.to_thread.run_sync(occupy_worker, anyio_started)
    )
    try:
        await asyncio.wait_for(
            asyncio.gather(native_started.wait(), anyio_started.wait()), timeout=2
        )
        async with httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app), base_url="https://mcp.example.com"
        ) as client:
            response = await asyncio.wait_for(
                client.post("/mcp", headers={"Authorization": f"Bearer {token}"}),
                timeout=1,
            )
            assert response.status_code == 202
            rejected = await asyncio.wait_for(
                client.post("/mcp", headers={"Authorization": "Bearer invalid"}),
                timeout=1,
            )
            assert rejected.status_code == 401
    finally:
        limiter.total_tokens = previous_tokens
        release.set()
        await asyncio.wait_for(
            asyncio.gather(native_worker, anyio_worker, return_exceptions=True),
            timeout=2,
        )


@dataclass
class _AuthenticatedHTTP:
    client: TestClient
    signing_key: rsa.RSAPrivateKey
    forwarded: list[TimeBaseCredentials]

    def token(self, **claims: Any) -> str:
        return jwt.encode(
            {
                "iss": _ISSUER,
                "aud": _AUDIENCE,
                "sub": "user-1",
                "azp": "registered-client",
                "preferred_username": "alice",
                "exp": int(time.time()) + 300,
                "scp": "mcp.access",
                **claims,
            },
            self.signing_key,
            algorithm="RS256",
        )


@pytest.fixture
def authenticated_http(monkeypatch: pytest.MonkeyPatch) -> Iterator[_AuthenticatedHTTP]:
    signing_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_jwk = jwt.PyJWK.from_json(RSAAlgorithm.to_jwk(signing_key.public_key()))

    def signing_key_from_jwt(
        _client: jwt.PyJWKClient, _token: str | bytes
    ) -> jwt.PyJWK:
        return public_jwk

    monkeypatch.setattr(
        jwt.PyJWKClient, "get_signing_key_from_jwt", signing_key_from_jwt
    )
    forwarded: list[TimeBaseCredentials] = []

    class RecordingClient(StubTimeBaseClient):
        def __init__(self, instance: TimeBaseInstanceRuntime) -> None:
            super().__init__(instance)
            forwarded.append(resolve_timebase_credentials(instance))

        @override
        def list_stream_infos(
            self, offset: int, limit: int
        ) -> tuple[int, list[StreamInfo]]:
            return 1, [StreamInfo(key="bars")][offset : offset + limit]

    monkeypatch.setattr(
        "timebase_mcp.clients.factory.create_timebase_client", RecordingClient
    )
    settings = MCPSettings(
        transport="streamable-http",
        auth_issuer_url=_ISSUER,
        auth_jwks_url=f"{_ISSUER}/keys",
        auth_audience=_AUDIENCE,
        auth_public_url=_RESOURCE,
        auth_required_scopes=[_SCOPE],
        auth_scope_aliases={_SCOPE: "mcp.access"},
        tb_auth_mode="forward_identity",
        tb_url="dxtick://timebase.internal:8011",
    )
    app = create_server(settings).streamable_http_app(
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=False,
        ),
    )
    with TestClient(app, base_url="https://mcp.example.com") as client:
        yield _AuthenticatedHTTP(client, signing_key, forwarded)


def _tool_request() -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "list_streams",
            "arguments": {},
            "_meta": _CLIENT_META,
        },
    }


def _assert_streams_read(response: httpx2.Response) -> None:
    assert response.status_code == 200
    payload = parse_jsonrpc_response(response)
    assert payload is not None
    result = payload["result"]
    assert result["isError"] is False
    assert result["structuredContent"]["streams"][0]["key"] == "bars"


def test_http_auth_advertises_canonical_scope_and_forwards_original_token(
    authenticated_http: _AuthenticatedHTTP,
) -> None:
    client = authenticated_http.client
    headers = build_modern_headers(method="tools/call", mcp_name="list_streams")
    challenge = client.post("/mcp", json=_tool_request(), headers=headers)
    assert challenge.status_code == 401
    assert challenge.headers["www-authenticate"].startswith("Bearer ")
    metadata_url = (
        challenge.headers["www-authenticate"]
        .split('resource_metadata="')[1]
        .split('"')[0]
    )
    metadata = client.get(metadata_url)
    assert metadata.status_code == 200
    assert metadata.json()["resource"] == _RESOURCE
    assert metadata.json()["scopes_supported"] == [_SCOPE]
    assert metadata.json()["authorization_servers"] == [_ISSUER]

    token = authenticated_http.token()
    headers["authorization"] = f"Bearer {token}"
    response = client.post("/mcp", json=_tool_request(), headers=headers)
    _assert_streams_read(response)
    assert authenticated_http.forwarded == [
        TimeBaseCredentials(kind="bearer", username="alice", token=token)
    ]


@pytest.mark.parametrize(
    "claims",
    [
        {"scp": None},
        {"scp": "unrelated"},
        {"scp": None, "roles": [_SCOPE]},
    ],
    ids=["missing-delegated-scope", "wrong-delegated-scope", "canonical-role-only"],
)
def test_http_auth_rejects_tokens_without_mapped_delegated_scope(
    authenticated_http: _AuthenticatedHTTP, claims: dict[str, Any]
) -> None:
    headers = build_modern_headers(method="tools/call", mcp_name="list_streams")
    headers["authorization"] = f"Bearer {authenticated_http.token(**claims)}"
    response = authenticated_http.client.post(
        "/mcp", json=_tool_request(), headers=headers
    )
    assert response.status_code == 401
    assert authenticated_http.forwarded == []


class _MemoryTokenStorage:
    def __init__(self) -> None:
        self.tokens: OAuthToken | None = None
        self.client_info = OAuthClientInformationFull.model_validate(
            {
                "client_id": "registered-client",
                "token_endpoint_auth_method": "none",
                "redirect_uris": ["http://127.0.0.1:8765/callback"],
                "issuer": _ISSUER,
            }
        )

    async def get_tokens(self) -> OAuthToken | None:
        return self.tokens

    async def set_tokens(self, tokens: OAuthToken) -> None:
        self.tokens = tokens

    async def get_client_info(self) -> OAuthClientInformationFull:
        return self.client_info

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        raise AssertionError("The reference client must use its static registration")


@pytest.mark.anyio
async def test_python_sdk_requests_full_scope_and_refreshes_forwarded_identity(
    authenticated_http: _AuthenticatedHTTP,
) -> None:
    authorization_urls: list[str] = []
    token_requests: list[dict[str, list[str]]] = []
    initial_token = authenticated_http.token(jti="initial")
    refreshed_token = authenticated_http.token(jti="refreshed")
    token_endpoint = "https://login.example.com/tenant/oauth2/v2.0/token"

    async def redirect_handler(url: str) -> None:
        authorization_urls.append(url)

    async def callback_handler() -> AuthorizationCodeResult:
        params = parse_qs(urlparse(authorization_urls[-1]).query)
        return AuthorizationCodeResult(code="test-code", state=params["state"][0])

    def handle_request(request: httpx2.Request) -> httpx2.Response:
        if request.url.host == "mcp.example.com":
            response = authenticated_http.client.request(
                request.method,
                str(request.url),
                headers=dict(request.headers),
                content=request.content,
            )
            return httpx2.Response(
                response.status_code,
                headers=dict(response.headers),
                content=response.content,
            )
        if str(request.url) == f"{_ISSUER}/.well-known/openid-configuration":
            return httpx2.Response(
                200,
                json={
                    "issuer": _ISSUER,
                    "authorization_endpoint": (
                        "https://login.example.com/tenant/oauth2/v2.0/authorize"
                    ),
                    "token_endpoint": token_endpoint,
                    "response_types_supported": ["code"],
                    "grant_types_supported": ["authorization_code", "refresh_token"],
                    "scopes_supported": ["openid", "profile", "offline_access", _SCOPE],
                    "token_endpoint_auth_methods_supported": ["none"],
                },
            )
        if request.method == "GET" and "/.well-known/" in request.url.path:
            return httpx2.Response(404)
        assert request.method == "POST" and str(request.url) == token_endpoint
        params = parse_qs(request.content.decode())
        token_requests.append(params)
        if params["grant_type"] == ["authorization_code"]:
            return httpx2.Response(
                200,
                json={
                    "access_token": initial_token,
                    "token_type": "Bearer",
                    "expires_in": 300,
                    "refresh_token": "test-refresh-token",
                },
            )
        assert params["grant_type"] == ["refresh_token"]
        assert params["refresh_token"] == ["test-refresh-token"]
        return httpx2.Response(
            200,
            json={
                "access_token": refreshed_token,
                "token_type": "Bearer",
                "expires_in": 300,
            },
        )

    storage = _MemoryTokenStorage()
    provider = OAuthClientProvider(
        server_url=_RESOURCE,
        client_metadata=OAuthClientMetadata.model_validate(
            {
                "redirect_uris": ["http://127.0.0.1:8765/callback"],
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
                "token_endpoint_auth_method": "none",
            }
        ),
        storage=storage,
        redirect_handler=redirect_handler,
        callback_handler=callback_handler,
    )
    async with httpx2.AsyncClient(
        auth=provider, transport=httpx2.MockTransport(handle_request)
    ) as client:
        discovered = await client.post(
            _RESOURCE,
            headers=build_modern_headers(method="server/discover"),
            json={
                "jsonrpc": "2.0",
                "id": 0,
                "method": "server/discover",
                "params": {"_meta": _CLIENT_META},
            },
        )
        assert discovered.status_code == 200
        discovery_payload = parse_jsonrpc_response(discovered)
        assert discovery_payload is not None
        assert "tools" in discovery_payload["result"]["capabilities"]

        headers = build_modern_headers(method="tools/call", mcp_name="list_streams")
        first = await client.post(_RESOURCE, headers=headers, json=_tool_request())
        _assert_streams_read(first)
        provider.context.token_expiry_time = 1
        second = await client.post(_RESOURCE, headers=headers, json=_tool_request())
        _assert_streams_read(second)

    assert len(authorization_urls) == 1
    authorization = parse_qs(urlparse(authorization_urls[0]).query)
    assert authorization["client_id"] == ["registered-client"]
    assert authorization["resource"] == [_RESOURCE]
    assert authorization["scope"] == [f"{_SCOPE} offline_access"]
    assert authorization["code_challenge_method"] == ["S256"]
    assert len(authorization["code_challenge"][0]) == 43
    assert [params["resource"] for params in token_requests] == [[_RESOURCE]] * 2
    assert token_requests[0]["code"] == ["test-code"]
    assert len(token_requests[0]["code_verifier"][0]) >= 43
    assert all("scope" not in params for params in token_requests)
    assert [credentials.token for credentials in authenticated_http.forwarded] == [
        initial_token,
        refreshed_token,
    ]
    assert [credentials.username for credentials in authenticated_http.forwarded] == [
        "alice",
        "alice",
    ]
    assert storage.tokens is not None
    assert storage.tokens.access_token == refreshed_token
    assert storage.tokens.scope == f"{_SCOPE} offline_access"
    assert storage.tokens.refresh_token == "test-refresh-token"
