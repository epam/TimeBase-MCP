"""Shared test doubles for TimeBase client contracts.

``StubTimeBaseClient`` implements the adapter ABC with no-op open/close and
``NotImplementedError`` on data methods. Override only the methods a test
exercises.

``StubPooledClient`` is the runtime pool surface (``ClosableClient``): close,
interrupt, bind, cancel. It is not a ``TimeBaseClient``.
"""

from __future__ import annotations

import threading
from datetime import datetime
from typing import Any
from typing_extensions import override

from timebase_mcp.clients.base import TimeBaseClient
from timebase_mcp.constants import DEFAULT_INSTANCE_KEY
from timebase_mcp.errors import TimeBaseOperationCancelledError
from timebase_mcp.models.core import StreamInfo
from timebase_mcp.runtime.instance import (
    TimeBaseInstanceConfig,
    TimeBaseInstanceRuntime,
)


def stub_instance(
    *,
    key: str = DEFAULT_INSTANCE_KEY,
    config: TimeBaseInstanceConfig | None = None,
    read_only: bool = False,
) -> TimeBaseInstanceRuntime:
    return TimeBaseInstanceRuntime(
        key=key,
        config=config
        or TimeBaseInstanceConfig(
            tb_url="dxtick://localhost:8011",
            read_only=read_only,
        ),
    )


class StubTimeBaseClient(TimeBaseClient):
    def __init__(
        self,
        instance: TimeBaseInstanceRuntime | None = None,
    ) -> None:
        super().__init__(instance or stub_instance())

    @override
    def open(self) -> object:
        return object()

    @override
    def close(self) -> None:
        return None

    @override
    def require_db(self) -> object:
        return object()

    @override
    def get_stream(self, stream_key: str) -> Any:
        raise NotImplementedError

    @override
    def get_stream_schema_text(self, stream: Any) -> str:
        raise NotImplementedError

    @override
    def list_stream_symbols(self, stream: Any) -> list[str]:
        raise NotImplementedError

    @override
    def list_stream_infos(self) -> list[StreamInfo]:
        raise NotImplementedError

    @override
    def get_stream_time_range(
        self,
        stream_key: str,
        stream: Any,
    ) -> tuple[datetime | None, datetime | None]:
        raise NotImplementedError

    @override
    def list_stream_spaces(self, stream: Any) -> list[str] | None:
        raise NotImplementedError

    @override
    def get_stream_space_time_range(
        self,
        stream_key: str,
        stream: Any,
        space: str,
    ) -> tuple[datetime | None, datetime | None]:
        raise NotImplementedError

    @override
    def read_stream_messages(
        self,
        stream: Any,
        reverse: bool,
        count: int,
        space: str | None,
    ) -> list[dict[str, Any]]:
        raise NotImplementedError

    @override
    def read_query_messages(self, query_text: str, limit: int) -> list[dict[str, Any]]:
        raise NotImplementedError

    @override
    def compile_query_tokens(self, query_text: str) -> list[Any]:
        raise NotImplementedError


class StubPooledClient:
    """Duck-typed client for ``TimeBaseConnectionPool`` / ``run_with_runtime``."""

    def __init__(self, *, key: str) -> None:
        self.key = key
        self.close_calls = 0
        self.interrupt_calls = 0
        self.request_cancel_calls = 0
        self.rows_read = 0
        self.closed_event = threading.Event()
        self._closed = False
        self._cancel_event: threading.Event | None = None

    def close(self) -> None:
        if self._closed:
            return

        self._closed = True
        self.close_calls += 1
        self.closed_event.set()

    def interrupt(self) -> None:
        self.interrupt_calls += 1
        self.close()

    def bind_operation(self) -> None:
        self._cancel_event = threading.Event()
        self.rows_read = 0

    def request_cancel(self) -> None:
        self.request_cancel_calls += 1
        if self._cancel_event is not None:
            self._cancel_event.set()

    @property
    def cancel_requested(self) -> bool:
        return self._cancel_event is not None and self._cancel_event.is_set()

    def raise_if_cancelled(self) -> None:
        if self.cancel_requested:
            raise TimeBaseOperationCancelledError(
                "TimeBase operation was stopped before it returned a complete result."
            )
