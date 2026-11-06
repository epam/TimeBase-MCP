from __future__ import annotations

import os
from collections.abc import AsyncGenerator

import pytest
from mcp.client import Client

from tests.integration.support import SeededStream, seed_bars_stream, wait_for_timebase
from timebase_mcp.config.settings import MCPSettings
from timebase_mcp.server import create_server


@pytest.fixture(scope="session")
def integration_ping_url() -> str | None:
    return os.environ.get("TIMEBASE_PING_URL", "").strip() or None


@pytest.fixture(scope="session")
def integration_settings(integration_ping_url: str | None) -> MCPSettings:
    settings = MCPSettings()
    wait_for_timebase(settings, ping_url=integration_ping_url)
    return settings


@pytest.fixture(scope="session")
def seeded_stream(integration_settings: MCPSettings) -> SeededStream:
    return seed_bars_stream(integration_settings)


@pytest.fixture(scope="session")
def seeded_catalog(
    integration_settings: MCPSettings, seeded_stream: SeededStream
) -> None:
    seed_bars_stream(
        integration_settings, stream_key=f"{seeded_stream.stream_key}_catalog"
    )


@pytest.fixture
async def client_session(
    integration_settings: MCPSettings,
    seeded_stream: SeededStream,
) -> AsyncGenerator[Client]:
    server = create_server(integration_settings)
    async with Client(server, raise_exceptions=True) as session:
        yield session
