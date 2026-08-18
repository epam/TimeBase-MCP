from __future__ import annotations

import logging

import pytest

from timebase_mcp.config.env import SettingsEnv
from timebase_mcp.config.settings import MCPSettings
from timebase_mcp.server import create_server


def test_remote_unauthenticated_bind_logs_warning(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv(SettingsEnv.MCP_TRANSPORT, "streamable-http")
    monkeypatch.setenv(SettingsEnv.MCP_HOST, "0.0.0.0")

    with caplog.at_level(logging.WARNING):
        create_server(MCPSettings())

    assert any(
        "unauthenticated HTTP MCP server" in record.message for record in caplog.records
    )
