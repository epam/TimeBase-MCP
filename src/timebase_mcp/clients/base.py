from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from contextlib import AbstractContextManager
from datetime import datetime
from types import TracebackType
from typing import Any, Literal
from typing_extensions import override

from timebase_mcp.errors import TimeBaseOperationCancelledError
from timebase_mcp.models.core import StreamInfo
from timebase_mcp.runtime.instance import TimeBaseInstanceRuntime


class TimeBaseClient(AbstractContextManager["TimeBaseClient"], ABC):
    """Client contract for TimeBase operations.

    Implementations expose low-level adapter primitives. Service modules own
    user-facing orchestration such as sorting, pagination, previews, and result
    model assembly.
    """

    def __init__(
        self,
        instance: TimeBaseInstanceRuntime,
    ) -> None:
        self._instance = instance
        self._cancel_event: threading.Event | None = None
        self._rows_read: int = 0

    @override
    def __enter__(self) -> "TimeBaseClient":
        self.open()
        return self

    @override
    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> Literal[False]:
        self.close()
        return False

    @abstractmethod
    def open(self) -> Any:
        """Opens a TimeBase connection."""

    @abstractmethod
    def close(self) -> None:
        """Closes the TimeBase connection."""

    def interrupt(self) -> None:
        """Interrupts an in-flight operation by closing the connection."""
        self.close()

    def bind_operation(self) -> None:
        """Resets cancellation state before an operation is dispatched."""
        self._cancel_event = threading.Event()
        self._rows_read = 0

    @property
    def cancel_requested(self) -> bool:
        """Whether cooperative cancellation was requested for this operation."""
        event = self._cancel_event
        return event is not None and event.is_set()

    def request_cancel(self) -> None:
        """Signals the in-flight read loop to stop."""
        if self._cancel_event is None:
            self._cancel_event = threading.Event()
        self._cancel_event.set()

    def raise_if_cancelled(self) -> None:
        """Fails if this operation was stopped, so partial data is never returned."""
        if self.cancel_requested:
            raise TimeBaseOperationCancelledError(
                "TimeBase operation was stopped before it returned a complete result."
            )

    @property
    def instance_key(self) -> str:
        """Key of the TimeBase instance this client is connected to."""
        return self._instance.key

    @property
    def read_only(self) -> bool:
        """Whether this instance is configured to be read-only."""
        return self._instance.config.read_only

    @property
    def rows_read(self) -> int:
        """Rows read so far by the current operation, for progress reporting."""
        return self._rows_read

    @abstractmethod
    def require_db(self) -> Any:
        """Returns an open TimeBase connection."""

    @abstractmethod
    def get_stream(self, stream_key: str) -> Any:
        """Returns a stream by key or raises StreamNotFoundError."""

    @abstractmethod
    def get_stream_schema_text(self, stream: Any) -> str:
        """Returns the text for a stream schema."""

    @abstractmethod
    def list_stream_symbols(self, stream: Any) -> list[str]:
        """Returns stream symbols/entities in adapter-native order.

        Deterministic sorting is owned by services.streams.
        """

    @abstractmethod
    def list_stream_infos(self) -> list[StreamInfo]:
        """Returns available streams in adapter-native order.

        Deterministic sorting is owned by services.streams.
        """

    @abstractmethod
    def get_stream_time_range(
        self,
        stream_key: str,
        stream: Any,
    ) -> tuple[datetime | None, datetime | None]:
        """Returns the UTC time range for a stream."""

    @abstractmethod
    def list_stream_spaces(self, stream: Any) -> list[str] | None:
        """Returns stream spaces in adapter-native order.

        Return None when the stream does not support spaces. Deterministic
        sorting is owned by services.streams.
        """

    @abstractmethod
    def get_stream_space_time_range(
        self,
        stream_key: str,
        stream: Any,
        space: str,
    ) -> tuple[datetime | None, datetime | None]:
        """Returns the UTC time range for a stream space."""

    @abstractmethod
    def read_stream_messages(
        self,
        stream: Any,
        reverse: bool,
        count: int,
        space: str | None,
    ) -> list[dict[str, Any]]:
        """Read stream messages for preview output."""

    @abstractmethod
    def read_query_messages(self, query_text: str, limit: int) -> list[dict[str, Any]]:
        """Read query messages for preview output."""

    @abstractmethod
    def compile_query_tokens(self, query_text: str) -> list[Any]:
        """Compile QQL and return raw token objects."""
