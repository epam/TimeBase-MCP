from __future__ import annotations

import pytest
from mcp.server.auth.middleware.auth_context import auth_context_var
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
from mcp.server.auth.provider import AccessToken

from tests.auth.helpers import (
    forward_identity_settings,
)
from tests.stubs import StubPooledClient
from timebase_mcp.errors import TimeBaseOperationStateError
from timebase_mcp.runtime.operations import run_with_runtime
from timebase_mcp.runtime.state import build_runtime


@pytest.mark.anyio
async def test_forward_identity_does_not_keep_idle_connections(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created_clients: list[StubPooledClient] = []

    def build_client(instance):
        client = StubPooledClient(key=instance.key)
        created_clients.append(client)
        return client

    monkeypatch.setattr(
        "timebase_mcp.clients.factory.create_timebase_client", build_client
    )

    runtime = build_runtime(forward_identity_settings())

    access = AccessToken(
        token="caller-jwt",
        client_id="cid",
        scopes=[],
        subject="user-1",
        claims={"preferred_username": "alice"},
    )
    reset = auth_context_var.set(AuthenticatedUser(access))
    try:
        first_client_id = await run_with_runtime(runtime, lambda client: id(client))
        second_client_id = await run_with_runtime(runtime, lambda client: id(client))
    finally:
        auth_context_var.reset(reset)

    assert first_client_id != second_client_id
    assert len(created_clients) == 2
    assert created_clients[0].close_calls == 1
    assert created_clients[1].close_calls == 1

    await runtime.aclose()


@pytest.mark.anyio
async def test_forward_identity_uses_per_principal_pool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list = []

    def build_client(instance):
        captured.append(instance.config)
        return StubPooledClient(key=instance.key)

    monkeypatch.setattr(
        "timebase_mcp.clients.factory.create_timebase_client", build_client
    )

    runtime = build_runtime(forward_identity_settings())
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
    created_clients: list[StubPooledClient] = []

    def build_client(instance):
        captured.append(instance.config)
        client = StubPooledClient(key=instance.key)
        created_clients.append(client)
        return client

    monkeypatch.setattr(
        "timebase_mcp.clients.factory.create_timebase_client", build_client
    )

    runtime = build_runtime(forward_identity_settings())

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
    runtime = build_runtime(forward_identity_settings())

    with pytest.raises(TimeBaseOperationStateError, match="not authenticated"):
        await run_with_runtime(runtime, lambda client: id(client))

    await runtime.aclose()
