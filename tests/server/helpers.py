from __future__ import annotations

import threading
import time
from datetime import datetime
from typing import Any

from mcp_types import TextResourceContents
from typing_extensions import override

from tests.stubs import StubPooledClient, StubTimeBaseClient
from timebase_mcp.constants import DEFAULT_INSTANCE_KEY
from timebase_mcp.models.core import StreamInfo

LOCAL_TOOL_NAMES = frozenset({"list_timebase_instances", "get_server_configuration"})


class ResourceCatalogClient(StubTimeBaseClient):
    def __init__(
        self,
        *,
        instance_key: str | None,
        description: str | None = None,
    ) -> None:
        super().__init__()
        self._instance_key = instance_key
        self._description = (
            description if description is not None else f"desc:{instance_key}"
        )

    @override
    def list_stream_infos(self) -> list[StreamInfo]:
        return [StreamInfo(key="bars", description=self._description)]

    @override
    def get_stream(self, stream_key: str) -> str:
        return stream_key

    @override
    def get_stream_schema_text(self, stream: str) -> str:
        return f"schema:{self._instance_key}:{stream}"


class SpaceToolClient(StubTimeBaseClient):
    def __init__(self, calls: list[tuple[str, str, str | None]]) -> None:
        super().__init__()
        self._calls = calls

    @override
    def get_stream(self, stream_key: str) -> str:
        return stream_key

    @override
    def list_stream_spaces(self, stream: str) -> list[str]:
        self._calls.append(("spaces", stream, None))
        return ["", "blue"]

    @override
    def get_stream_space_time_range(
        self,
        stream_key: str,
        stream: str,
        space: str,
    ) -> tuple[datetime | None, datetime | None]:
        self._calls.append(("space_range", stream_key, space))
        return None, None

    @override
    def read_stream_messages(
        self,
        stream: str,
        reverse: bool,
        count: int,
        space: str | None,
    ) -> list[dict[str, Any]]:
        assert reverse is True
        assert count == 3
        self._calls.append(("messages", stream, space))
        return [{"text": f"messages:{stream}:{space}"}]


def resource_text(result: Any) -> list[str]:
    return [
        content.text
        for content in result.contents
        if isinstance(content, TextResourceContents)
    ]


class QueryStubClient(StubPooledClient):
    """Pooled-client stand-in whose query read is driven by the cancel flag."""

    def __init__(self, *, block_until_cancelled: bool) -> None:
        super().__init__(key=DEFAULT_INSTANCE_KEY)
        self.block_until_cancelled = block_until_cancelled
        self.read_only = False
        self.read_started = threading.Event()
        self.read_finished = threading.Event()

    def read_query_messages(
        self, query_text: str, limit: int
    ) -> list[dict[str, object]]:
        self.read_started.set()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if self.cancel_requested:
                break
            if not self.block_until_cancelled and self.rows_read >= 3:
                break
            time.sleep(0.02)
            self.rows_read += 1
        self.read_finished.set()
        return [{"type": "Row", "n": index} for index in range(self.rows_read)]
