from __future__ import annotations

from collections.abc import AsyncGenerator, Callable
from contextlib import AbstractAsyncContextManager

import pytest
from mcp.client import Client

from timebase_mcp.config.settings import MCPSettings
from timebase_mcp.server import create_server


@pytest.fixture
def client_session_factory() -> Callable[
    [MCPSettings | None],
    AbstractAsyncContextManager[Client],
]:
    def build(
        settings: MCPSettings | None = None,
    ) -> AbstractAsyncContextManager[Client]:
        server = create_server(settings or MCPSettings())
        return Client(server, raise_exceptions=True)

    return build


@pytest.fixture
async def client_session(
    client_session_factory: Callable[
        [MCPSettings | None],
        AbstractAsyncContextManager[Client],
    ],
) -> AsyncGenerator[Client]:
    async with client_session_factory(None) as session:
        yield session
