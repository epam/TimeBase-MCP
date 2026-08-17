from __future__ import annotations

import asyncio

import pytest
from mcp.client import Client

import timebase_mcp.runtime.operations as operations_module
from timebase_mcp.config.settings import MCPSettings
from timebase_mcp.server import create_server

from tests.server.helpers import (
    QueryStubClient,
)


@pytest.mark.anyio
async def test_execute_query_reports_progress_to_a_real_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(operations_module, "_PROGRESS_INTERVAL_SECONDS", 0.02)
    stub = QueryStubClient(block_until_cancelled=False)
    monkeypatch.setattr(
        "timebase_mcp.clients.factory.create_timebase_client", lambda _instance: stub
    )

    updates: list[tuple[float, str | None]] = []

    async def on_progress(
        progress: float, total: float | None, message: str | None
    ) -> None:
        updates.append((progress, message))

    server = create_server(MCPSettings())
    async with Client(server, raise_exceptions=True) as client_session:
        result = await client_session.call_tool(
            "execute_query",
            {"query": 'select * from "bars"'},
            progress_callback=on_progress,
        )

    assert result.is_error is False
    assert updates, "no progress reached the client"
    values = [progress for progress, _ in updates]
    assert values == sorted(values)
    assert len(set(values)) == len(values)
    assert all("elapsed" in (message or "") for _, message in updates)


@pytest.mark.anyio
async def test_client_cancel_stops_execute_query_cooperatively(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub = QueryStubClient(block_until_cancelled=True)
    monkeypatch.setattr(
        "timebase_mcp.clients.factory.create_timebase_client", lambda _instance: stub
    )

    server = create_server(MCPSettings())
    async with Client(server, raise_exceptions=False) as client_session:
        call = asyncio.create_task(
            client_session.call_tool("execute_query", {"query": 'select * from "bars"'})
        )
        await asyncio.to_thread(stub.read_started.wait, 5)

        call.cancel()
        with pytest.raises(asyncio.CancelledError):
            await call

        await asyncio.to_thread(stub.read_finished.wait, 5)

        assert stub.request_cancel_calls >= 1
        assert stub.interrupt_calls == 0
        assert stub.close_calls == 0
