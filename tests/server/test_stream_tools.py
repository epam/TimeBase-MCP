from __future__ import annotations

import base64
import json
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager

import pytest
from mcp.client import Client
from mcp_types import TextContent, TextResourceContents
from typing_extensions import override

from tests.server.helpers import (
    SpaceToolClient,
)
from tests.stubs import StubTimeBaseClient
from timebase_mcp.config.settings import MCPSettings
from timebase_mcp.models.core import StreamCatalog, StreamInfo, StreamSymbols
from timebase_mcp.server import create_server
from timebase_mcp.tools import streams as stream_tools


@pytest.fixture
def multi_instance_settings() -> MCPSettings:
    return MCPSettings.model_validate(
        {
            "servers": [
                {"name": "prod", "url": "dxtick://prod:8011"},
                {"name": "dev", "url": "dxtick://dev:8011"},
            ]
        }
    )


@pytest.mark.anyio
async def test_catalog_tool_and_resources_are_bounded_and_share_scoped_cursors(
    monkeypatch: pytest.MonkeyPatch,
    multi_instance_settings: MCPSettings,
) -> None:
    class CatalogClient(StubTimeBaseClient):
        @override
        def list_stream_infos(
            self, offset: int, limit: int
        ) -> tuple[int, list[StreamInfo]]:
            streams = [
                StreamInfo(key=f"s{i:03d}", description=f"from {self.instance_key}")
                for i in reversed(range(103))
            ]
            return len(streams), streams[offset : offset + limit]

    monkeypatch.setattr(
        "timebase_mcp.clients.factory.create_timebase_client", CatalogClient
    )
    async with Client(
        create_server(multi_instance_settings), raise_exceptions=False
    ) as session:
        result = await session.call_tool(
            "list_streams", {"instance_key": "prod", "limit": 2}
        )
        first = StreamCatalog.model_validate(result.structured_content)
        assert first.returned_count == 2 and first.total_streams == 103
        assert [s.key for s in first.streams] == ["s102", "s101"]
        assert [s.description for s in first.streams] == ["from prod", "from prod"]
        cursor = first.next_cursor
        assert cursor is not None
        next_result = await session.call_tool(
            "list_streams", {"instance_key": "prod", "limit": 2, "cursor": cursor}
        )
        second = StreamCatalog.model_validate(next_result.structured_content)
        assert [s.key for s in second.streams] == ["s100", "s099"]
        wrong = await session.call_tool(
            "list_streams", {"instance_key": "dev", "cursor": cursor}
        )
        assert wrong.is_error
        assert "different TimeBase instance" in " ".join(
            c.text for c in wrong.content if isinstance(c, TextContent)
        )
        resource = await session.read_resource("timebase://instances/prod/streams")
        text = "\n".join(
            c.text for c in resource.contents if isinstance(c, TextResourceContents)
        )
        assert "s003:" in text and "s002:" not in text
        args = json.loads(text.split("using arguments: ")[1])
        assert args["instance_key"] == "prod"
        last_result = await session.call_tool("list_streams", args)
        last = StreamCatalog.model_validate(last_result.structured_content)
        assert [s.key for s in last.streams] == ["s002", "s001", "s000"]


@pytest.mark.anyio
async def test_symbol_tool_rejects_legacy_and_cross_instance_cursors(
    monkeypatch: pytest.MonkeyPatch,
    multi_instance_settings: MCPSettings,
) -> None:
    calls: list[tuple[str, str, int, int]] = []

    class SymbolClient(StubTimeBaseClient):
        @override
        def list_stream_symbols(
            self, stream_key: str, offset: int, limit: int
        ) -> tuple[int, list[str]]:
            calls.append((self.instance_key, stream_key, offset, limit))
            symbols = ["SYM1", "SYM2", "SYM10"]
            return len(symbols), symbols[offset : offset + limit]

    monkeypatch.setattr(
        "timebase_mcp.clients.factory.create_timebase_client", SymbolClient
    )
    async with Client(
        create_server(multi_instance_settings), raise_exceptions=False
    ) as session:
        arguments = {"stream_key": "bars", "instance_key": "prod", "limit": 1}
        first_result = await session.call_tool("get_stream_symbols", arguments)
        assert not first_result.is_error
        first = StreamSymbols.model_validate(first_result.structured_content)
        assert first.symbols == ["SYM1"]
        cursor = first.next_cursor
        assert cursor is not None
        next_page = await session.call_tool(
            "get_stream_symbols", {**arguments, "cursor": cursor}
        )
        assert not next_page.is_error
        second = StreamSymbols.model_validate(next_page.structured_content)
        assert second.symbols == ["SYM2"]
        legacy = base64.urlsafe_b64encode(
            json.dumps({"stream_key": "bars", "offset": 1, "total_symbols": 3}).encode()
        ).decode()
        old_result = await session.call_tool(
            "get_stream_symbols", {**arguments, "cursor": legacy}
        )
        other_result = await session.call_tool(
            "get_stream_symbols", {**arguments, "instance_key": "dev", "cursor": cursor}
        )
        assert old_result.is_error and other_result.is_error
        assert "Restart pagination without a cursor" in " ".join(
            c.text for c in old_result.content if isinstance(c, TextContent)
        )
        assert "different TimeBase instance" in " ".join(
            c.text for c in other_result.content if isinstance(c, TextContent)
        )
    assert calls == [("prod", "bars", 0, 1), ("prod", "bars", 1, 1)]


@pytest.mark.anyio
async def test_call_stream_tool_uses_single_instance_when_key_is_omitted(
    monkeypatch: pytest.MonkeyPatch,
    client_session_factory: Callable[
        [MCPSettings | None],
        AbstractAsyncContextManager[Client],
    ],
) -> None:
    selected_instances: list[str | None] = []

    async def run_list_streams(
        _ctx, _operation, *, instance_key=None, report_progress=False
    ):
        selected_instances.append(instance_key)
        return StreamCatalog()

    monkeypatch.setattr(stream_tools, "run_tool_operation", run_list_streams)

    async with client_session_factory(None) as client_session:
        result = await client_session.call_tool("list_streams", {})

    assert result.is_error is False
    assert selected_instances == [None]


@pytest.mark.anyio
async def test_call_stream_space_tools_pass_arguments(
    monkeypatch: pytest.MonkeyPatch,
    client_session_factory: Callable[
        [MCPSettings | None],
        AbstractAsyncContextManager[Client],
    ],
) -> None:
    selected_instances: list[str | None] = []
    calls: list[tuple[str, str, str | None]] = []

    async def run_stream_operation(
        _ctx, operation, *, instance_key=None, report_progress=False
    ):
        selected_instances.append(instance_key)
        return operation(SpaceToolClient(calls))

    monkeypatch.setattr(stream_tools, "run_tool_operation", run_stream_operation)

    async with client_session_factory(None) as client_session:
        spaces_result = await client_session.call_tool(
            "list_stream_spaces",
            {"stream_key": "bars", "instance_key": "dev"},
        )
        range_result = await client_session.call_tool(
            "get_stream_space_time_range",
            {"stream_key": "bars", "space": "blue", "instance_key": "dev"},
        )
        messages_result = await client_session.call_tool(
            "get_stream_messages",
            {
                "stream_key": "bars",
                "space": "blue",
                "reverse": True,
                "count": 3,
                "instance_key": "dev",
            },
        )

    assert spaces_result.is_error is False
    assert spaces_result.structured_content == {
        "stream_key": "bars",
        "spaces": ["", "blue"],
        "returned_count": 2,
        "supports_spaces": True,
    }
    assert range_result.is_error is False
    assert range_result.structured_content == {
        "stream_key": "bars",
        "space": "blue",
        "start": None,
        "end": None,
    }
    assert messages_result.is_error is False
    assert selected_instances == ["dev", "dev", "dev"]
    assert calls == [
        ("spaces", "bars", None),
        ("space_range", "bars", "blue"),
        ("messages", "bars", "blue"),
    ]


@pytest.mark.anyio
async def test_call_stream_tool_requires_instance_key_when_multiple_instances(
    multi_instance_settings: MCPSettings,
) -> None:
    server = create_server(multi_instance_settings)

    async with Client(server, raise_exceptions=False) as client_session:
        result = await client_session.call_tool("list_streams", {})

    text_content = [
        content.text for content in result.content if isinstance(content, TextContent)
    ]

    assert result.is_error is True
    assert result.structured_content is None
    assert text_content == [
        (
            "Error executing tool list_streams: "
            "instance_key is required when multiple TimeBase instances are configured. "
            "Call list_timebase_instances to choose an instance."
        )
    ]
