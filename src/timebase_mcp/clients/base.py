from __future__ import annotations

from abc import ABC, abstractmethod
from contextlib import AbstractContextManager
from datetime import datetime
from types import TracebackType
from typing import Any, Literal
from typing_extensions import override

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
        """Interruption of an in-flight operation."""
        self.close()

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
