from __future__ import annotations

from collections.abc import AsyncGenerator
import os

import pytest
from mcp.client.session import ClientSession
from mcp.shared.memory import create_connected_server_and_client_session

from tests.integration.support import seed_bars_stream, wait_for_timebase
from timebase_mcp.config import MCPSettings
from timebase_mcp.server import create_server


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(scope="session")
def integration_ping_url() -> str | None:
    ping_url = os.environ.get("TIMEBASE_PING_URL")
    if ping_url is None:
        return None

    normalized_ping_url = ping_url.strip()
    return normalized_ping_url or None


@pytest.fixture(scope="session")
def integration_settings(integration_ping_url: str | None) -> MCPSettings:
    settings = MCPSettings()
    wait_for_timebase(settings, ping_url=integration_ping_url)
    return settings


@pytest.fixture(scope="session")
def seeded_stream(integration_settings: MCPSettings):
    return seed_bars_stream(integration_settings)


@pytest.fixture
async def client_session(
    integration_settings: MCPSettings,
    seeded_stream,
) -> AsyncGenerator[ClientSession]:
    del seeded_stream

    server = create_server(integration_settings)
    async with create_connected_server_and_client_session(
        server,
        raise_exceptions=True,
    ) as session:
        yield session
