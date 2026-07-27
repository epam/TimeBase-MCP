from __future__ import annotations

import logging
from datetime import datetime
from typing_extensions import override
from typing import TYPE_CHECKING, Any, cast

from timebase_mcp.auth.outbound import resolve_timebase_credentials
from timebase_mcp.clients.base import TimeBaseClient
from timebase_mcp.clients.native.common import (
    call_cursor_context,
    connection_error_hint,
    normalize_message,
    parse_time_range_ms,
)
from timebase_mcp.errors import (
    ConfigurationError,
    StreamNotFoundError,
    TimeBaseConnectionError,
)
from timebase_mcp.models.core import StreamInfo
from timebase_mcp.runtime.instance import TimeBaseInstanceRuntime

if TYPE_CHECKING:
    import dxapi_ce as dxapi_ce_types

try:
    import dxapi_ce
except Exception as exc:
    dxapi_ce = None
    _DXAPI_CE_IMPORT_ERROR = exc
else:
    _DXAPI_CE_IMPORT_ERROR = None

logger = logging.getLogger(__name__)


class CommunityTimeBaseClient(TimeBaseClient):
    def __init__(
        self,
        instance: TimeBaseInstanceRuntime,
    ) -> None:
        super().__init__(instance)
        self._db: dxapi_ce_types.TickDb | None = None

    @override
    def open(self) -> dxapi_ce_types.TickDb:
        if self._db is not None and self._db.isOpen():
            return self._db

        self._ensure_dxapi_ce()
        assert dxapi_ce is not None

        try:
            credentials = resolve_timebase_credentials(
                self._instance,
                error_type="connection",
            )
            if credentials.kind == "bearer":
                assert credentials.username is not None
                assert credentials.token is not None
                db = dxapi_ce.TickDb.createFromUrl(
                    self._instance.config.tb_url,
                    credentials.username,
                    credentials.token,
                )
            elif credentials.kind == "basic":
                assert credentials.username is not None
                assert credentials.password is not None
                db = dxapi_ce.TickDb.createFromUrl(
                    self._instance.config.tb_url,
                    credentials.username,
                    credentials.password,
                )
            else:
                db = dxapi_ce.TickDb.createFromUrl(self._instance.config.tb_url)
            db.open(False)
        except Exception as exc:
            hint = connection_error_hint(self._instance, exc, edition="community")
            raise TimeBaseConnectionError(
                f"Failed to connect to TimeBase at '{self._instance.config.tb_url}': {exc}{hint}"
            ) from exc

        logger.info(
            "Connected to TimeBase via community client at %s",
            self._instance.config.tb_url,
        )
        self._db = db
        return db

    @override
    def close(self) -> None:
        if self._db is None:
            return

        try:
            self._db.close()
        finally:
            self._db = None

    @override
    def get_stream(self, stream_key: str) -> dxapi_ce_types.TickStream:
        stream = self.require_db().getStream(stream_key)
        if stream is None:
            raise StreamNotFoundError(stream_key)
        return stream

    @override
    def require_db(self) -> dxapi_ce_types.TickDb:
        if self._db is None or not self._db.isOpen():
            return self.open()
        return self._db

    @override
    def list_stream_infos(self) -> list[StreamInfo]:
        streams = self.require_db().listStreams()
        return [
            StreamInfo(key=stream.key(), description=stream.description())
            for stream in streams
        ]

    @override
    def get_stream_schema_text(self, stream: dxapi_ce_types.TickStream) -> str:
        return stream.describe()

    @override
    def list_stream_symbols(self, stream: dxapi_ce_types.TickStream) -> list[str]:
        return list[str](stream.listSymbols())

    @override
    def get_stream_time_range(
        self,
        stream_key: str,
        stream: dxapi_ce_types.TickStream,
    ) -> tuple[datetime | None, datetime | None]:
        return parse_time_range_ms(stream_key, stream.getTimeRange())

    @override
    def list_stream_spaces(self, stream: dxapi_ce_types.TickStream) -> list[str] | None:
        spaces = stream.listSpaces()
        if spaces is None:
            return None
        return list[str](spaces)

    @override
    def get_stream_space_time_range(
        self,
        stream_key: str,
        stream: dxapi_ce_types.TickStream,
        space: str,
    ) -> tuple[datetime | None, datetime | None]:
        return parse_time_range_ms(stream_key, stream.getSpaceTimeRange(space))

    @override
    def read_stream_messages(
        self,
        stream: dxapi_ce_types.TickStream,
        reverse: bool,
        count: int,
        space: str | None,
    ) -> list[dict[str, Any]]:
        self._ensure_dxapi_ce()
        assert dxapi_ce is not None
        options = dxapi_ce.SelectionOptions()
        options.live = False
        options.reverse = reverse
        if space is not None:
            options.space = space
        timestamp = (
            dxapi_ce.JAVA_LONG_MAX_VALUE if reverse else dxapi_ce.JAVA_LONG_MIN_VALUE
        )

        messages: list[dict[str, Any]] = []
        with call_cursor_context(
            stream.select,
            timestamp,
            options,
            None,
            None,
        ) as cursor:
            cursor = cast("dxapi_ce_types.TickCursor", cursor)
            while not self.cancel_requested and len(messages) < count and cursor.next():
                messages.append(normalize_message(cursor.getMessage()))

        if reverse:
            messages.reverse()

        return messages

    @override
    def read_query_messages(self, query_text: str, limit: int) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = []
        with call_cursor_context(
            self.require_db().tryExecuteQuery,
            query_text,
        ) as cursor:
            cursor = cast("dxapi_ce_types.TickCursor", cursor)
            while not self.cancel_requested and len(messages) < limit and cursor.next():
                messages.append(normalize_message(cursor.getMessage()))

        return messages

    @override
    def compile_query_tokens(self, query_text: str) -> list[Any]:
        return list[Any](self.require_db().compileQuery(query_text))

    def _ensure_dxapi_ce(self) -> None:
        if dxapi_ce is None:
            raise ConfigurationError(
                "Community edition requires installing timebase-mcp[community]"
            ) from _DXAPI_CE_IMPORT_ERROR
