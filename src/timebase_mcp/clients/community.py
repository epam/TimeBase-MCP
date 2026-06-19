from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, cast

from timebase_mcp.clients.base import TimeBaseClient
from timebase_mcp.errors import (
    ConfigurationError,
    StreamNotFoundError,
    TimeBaseConnectionError,
)
from timebase_mcp.instance import TimeBaseInstanceConfig

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
        config: TimeBaseInstanceConfig,
        *,
        read_only: bool = False,
    ) -> None:
        super().__init__(config, read_only=read_only)
        self._db: dxapi_ce_types.TickDb | None = None

    def open(self) -> dxapi_ce_types.TickDb:
        if self._db is not None and self._db.isOpen():
            return self._db

        self._ensure_dxapi_ce()
        assert dxapi_ce is not None
        password = None
        if self._config.tb_password is not None:
            password = self._config.tb_password.get_secret_value()

        try:
            if self._config.access_token is not None:
                username = (
                    self._config.access_token_username
                    or self._config.tb_username
                    or "oauth"
                )
                db = dxapi_ce.TickDb.createFromUrl(
                    self._config.tb_url, username, self._config.access_token
                )
            elif self._config.tb_username is None and password is None:
                db = dxapi_ce.TickDb.createFromUrl(self._config.tb_url)
            else:
                username = self._config.tb_username
                assert username is not None
                assert password is not None
                db = dxapi_ce.TickDb.createFromUrl(
                    self._config.tb_url, username, password
                )
            db.open(self._read_only)
        except Exception as exc:
            hint = self._connection_error_hint(exc)
            raise TimeBaseConnectionError(
                f"Failed to connect to TimeBase at '{self._config.tb_url}': {exc}{hint}"
            ) from exc

        logger.info(
            "Connected to TimeBase via community client at %s",
            self._config.tb_url,
        )
        self._db = db
        return db

    def _connection_error_hint(self, exc: Exception) -> str:
        message = str(exc)
        normalized = message.casefold()
        hints: list[str] = []

        if "certificate verification" in normalized or "ssl" in normalized:
            hints.append(
                "For TLS/certificate issues, use DXAPI_SSL_CERT_FILE with a DER "
                "certificate, or DXAPI_SSL_TRUST_ALL=true for non-production testing."
            )

        if "timed out" in normalized or "timeout" in normalized:
            hints.append(
                "If this TimeBase endpoint is behind an HTTPS/TLS terminator, "
                "set DXAPI_SSL_TERMINATION=true."
            )

        if "wrong username or password" in normalized and self._config.auth_mode in (
            "auto",
            "none",
        ):
            hints.append(
                "The server looks protected but MCP connected without credentials. "
                "Interactive OAuth requires the enterprise dxapi client."
            )

        if self._config.auto_auth_error:
            hints.append(
                f"OAuth auto-discovery failed earlier: {self._config.auto_auth_error}"
            )

        if not hints:
            return ""
        return " " + " ".join(hints)

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
