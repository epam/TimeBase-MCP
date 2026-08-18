from __future__ import annotations

import types
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from tests.stubs import StubPooledClient
from timebase_mcp.auth.discovery import (
    InteractiveEndpoints,
)
from timebase_mcp.auth.interactive import (
    InteractiveOAuthProvider,
)
from timebase_mcp.auth.token_verifier import (
    JwksTokenVerifier,
)
from timebase_mcp.config.settings import MCPSettings
from timebase_mcp.runtime.instance import (
    TimeBaseInstanceConfig,
    TimeBaseInstanceRuntime,
)


def make_rsa_verifier(
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


class DiscoveryResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return

    def json(self) -> dict[str, Any]:
        return self._payload


def timebase_oauthinfo_payload() -> dict[str, Any]:
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


def http_instance(
    *,
    tb_url: str = "dxtick://tb.example.com:8011",
    http_base_url: str | None = "https://tb.example.com:8011",
) -> TimeBaseInstanceRuntime:
    return TimeBaseInstanceRuntime(
        key="default",
        config=TimeBaseInstanceConfig(
            tb_url=tb_url,
            http_base_url=http_base_url,
        ),
    )


def forward_identity_settings() -> MCPSettings:
    return MCPSettings(
        transport="streamable-http",
        auth_audience="timebase-api",
        auth_public_url="https://mcp.example.com/mcp",
        tb_auth_mode="forward_identity",
    )


def interactive_provider(**kwargs: Any) -> InteractiveOAuthProvider:
    provider = InteractiveOAuthProvider(
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


def patch_auto_client_creation(
    monkeypatch: pytest.MonkeyPatch,
) -> list[TimeBaseInstanceConfig]:
    captured_configs: list[TimeBaseInstanceConfig] = []

    class _AutoClient(StubPooledClient):
        def __init__(self, instance: TimeBaseInstanceRuntime) -> None:
            super().__init__(key=instance.key)
            self.config = instance.config

        def open(self) -> None:
            return

    def fake_create_client(
        instance: TimeBaseInstanceRuntime,
        _edition: str,
    ) -> _AutoClient:
        captured_configs.append(instance.config)
        return _AutoClient(instance)

    monkeypatch.setattr(
        "timebase_mcp.clients.factory._create_client_for_edition",
        fake_create_client,
    )
    monkeypatch.setattr(
        "timebase_mcp.clients.factory._available_editions",
        lambda _statuses=None: ("community",),
    )
    return captured_configs


def advertise_oauth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "timebase_mcp.auth.outbound._resolve_interactive_endpoints",
        lambda **_kwargs: InteractiveEndpoints(
            authorization_endpoint="https://login.example/auth",
            token_endpoint="https://login.example/token",
            client_id="application-client",
            scope="openid",
            discovery_base_url="https://tb.example.com:8011",
        ),
    )
