from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, cast

from timebase_mcp.clients.base import TimeBaseClient
from timebase_mcp.config import MCPSettings
from timebase_mcp.errors import (
    ConfigurationError,
    StreamNotFoundError,
    TimeBaseConnectionError,
)

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
    def __init__(self, settings: MCPSettings, *, read_only: bool = True) -> None:
        super().__init__(settings, read_only=read_only)
        self._db: dxapi_ce_types.TickDb | None = None

    def open(self) -> dxapi_ce_types.TickDb:
        if self._db is not None and self._db.isOpen():
            return self._db

        self._ensure_dxapi_ce()
        assert dxapi_ce is not None
        password = None
        if self._settings.tb_password is not None:
            password = self._settings.tb_password.get_secret_value()

        try:
            if self._settings.tb_username is None and password is None:
                db = dxapi_ce.TickDb.createFromUrl(self._settings.tb_url)
            else:
                username = self._settings.tb_username
                assert username is not None
                assert password is not None
                db = dxapi_ce.TickDb.createFromUrl(
                    self._settings.tb_url, username, password
                )
            db.open(self._read_only)
        except Exception as exc:
            raise TimeBaseConnectionError(
                f"Failed to connect to TimeBase at '{self._settings.tb_url}': {exc}"
            ) from exc

        logger.info(
            "Connected to TimeBase via community client at %s",
            self._settings.tb_url,
        )
        self._db = db
        return db

    def close(self) -> None:
        if self._db is None:
            return

        try:
            self._db.close()
        finally:
            self._db = None

    def get_stream(self, stream_key: str) -> dxapi_ce_types.TickStream:
        stream = self._require_db().getStream(stream_key)
        # type:
        if stream is None:
            raise StreamNotFoundError(stream_key)
        return stream

    def _require_db(self) -> dxapi_ce_types.TickDb:
        if self._db is None or not self._db.isOpen():
            return self.open()
        return self._db

    def _get_stream_schema_text(self, stream: dxapi_ce_types.TickStream) -> str:
        return stream.describe()

    def _list_stream_symbols(self, stream: dxapi_ce_types.TickStream) -> list[str]:
        return list[str](stream.listSymbols())

    def _read_stream_messages(
        self,
        stream: dxapi_ce_types.TickStream,
        reverse: bool,
        count: int,
    ) -> list[dict[str, Any]]:
        self._ensure_dxapi_ce()
        assert dxapi_ce is not None
        options = dxapi_ce.SelectionOptions()
        options.live = False
        options.reverse = reverse
        timestamp = (
            dxapi_ce.JAVA_LONG_MAX_VALUE if reverse else dxapi_ce.JAVA_LONG_MIN_VALUE
        )

        messages: list[dict[str, Any]] = []
        with self._call_cursor_context(
            stream.select,
            timestamp,
            options,
            None,
            None,
        ) as cursor:
            cursor = cast("dxapi_ce_types.TickCursor", cursor)
            while len(messages) < count and cursor.next():
                messages.append(self._normalize_message(cursor.getMessage()))

        if reverse:
            messages.reverse()

        return messages

    def _read_query_messages(self, query_text: str, limit: int) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = []
        with self._call_cursor_context(
            self._require_db().tryExecuteQuery,
            query_text,
        ) as cursor:
            cursor = cast("dxapi_ce_types.TickCursor", cursor)
            while len(messages) < limit and cursor.next():
                messages.append(self._normalize_message(cursor.getMessage()))

        return messages

    def _compile_query_tokens(self, query_text: str) -> list[Any]:
        return list[Any](self._require_db().compileQuery(query_text))

    def _ensure_dxapi_ce(self) -> None:
        if dxapi_ce is None:
            raise ConfigurationError(
                "Community edition requires installing timebase-mcp[community]"
            ) from _DXAPI_CE_IMPORT_ERROR
