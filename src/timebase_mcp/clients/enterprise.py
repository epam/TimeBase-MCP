from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, cast

from timebase_mcp.clients.base import TimeBaseClient
from timebase_mcp.config import MCPSettings
from timebase_mcp.constants import APP_NAME
from timebase_mcp.errors import (
    ConfigurationError,
    StreamNotFoundError,
    TimeBaseConnectionError,
)
from timebase_mcp.oauth2 import (
    OAuth2AccessTokenProvider,
    get_oauth2_provider,
)

if TYPE_CHECKING:
    import dxapi as dxapi_types

try:
    import dxapi
except Exception as exc:
    dxapi = None
    _DXAPI_IMPORT_ERROR = exc
else:
    _DXAPI_IMPORT_ERROR = None

logger = logging.getLogger(__name__)


class EnterpriseTimeBaseClient(TimeBaseClient):
    def __init__(self, settings: MCPSettings, *, read_only: bool = True) -> None:
        super().__init__(settings, read_only=read_only)
        self._db: dxapi_types.TickDb | None = None
        self._oauth2_provider: OAuth2AccessTokenProvider | None = None

    def open(self) -> dxapi_types.TickDb:
        if self._db is not None and self._db.isOpen():
            return self._db

        self._ensure_dxapi()
        assert dxapi is not None

        try:
            oauth2_config = self._settings.oauth2_config
            if oauth2_config is not None:
                username = self._settings.tb_username
                assert username is not None

                try:
                    provider = get_oauth2_provider(
                        oauth2_config,
                        provider=self._oauth2_provider,
                    )
                    self._oauth2_provider = provider
                    access_token = provider.get_access_token()
                except (ValueError, PermissionError, ConnectionError) as exc:
                    raise TimeBaseConnectionError(
                        "Failed to obtain OAuth2 credentials for TimeBase at "
                        f"'{self._settings.tb_url}': {exc}"
                    ) from exc

                logger.debug(
                    "Obtained OAuth2 access token for TimeBase at %s using client ID %s",
                    self._settings.tb_url,
                    oauth2_config.client_id,
                )

                db = dxapi.TickDb.createFromUrl(
                    self._settings.tb_url,
                    username,
                    access_token,
                )
            else:
                password = None
                if self._settings.tb_password is not None:
                    password = self._settings.tb_password.get_secret_value()

                if self._settings.tb_username is None and password is None:
                    db = dxapi.TickDb.createFromUrl(self._settings.tb_url)
                else:
                    username = self._settings.tb_username
                    assert username is not None
                    assert password is not None
                    db = dxapi.TickDb.createFromUrl(
                        self._settings.tb_url, username, password
                    )

            db.setApplicationName(APP_NAME)
            db.open(self._read_only)
        except TimeBaseConnectionError:
            raise
        except Exception as exc:
            raise TimeBaseConnectionError(
                f"Failed to connect to TimeBase at '{self._settings.tb_url}': {exc}"
            ) from exc

        logger.info(
            "Connected to TimeBase via enterprise client at %s",
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

    def get_stream(self, stream_key: str) -> dxapi_types.TickStream:
        stream = self._require_db().getStream(stream_key)
        if stream is None:
            raise StreamNotFoundError(stream_key)
        return stream

    def _require_db(self) -> dxapi_types.TickDb:
        if self._db is None or not self._db.isOpen():
            return self.open()
        return self._db

    def _get_stream_schema_text(self, stream: dxapi_types.TickStream) -> str:
        return stream.describe()

    def _list_stream_symbols(self, stream: dxapi_types.TickStream) -> list[str]:
        return list[str](stream.listSymbols())

    def _read_stream_messages(
        self,
        stream: dxapi_types.TickStream,
        reverse: bool,
        count: int,
    ) -> list[dict[str, Any]]:
        self._ensure_dxapi()
        assert dxapi is not None
        options = dxapi.SelectionOptions()
        options.live = False
        options.reverse = reverse
        timestamp = dxapi.JAVA_LONG_MAX_VALUE if reverse else dxapi.JAVA_LONG_MIN_VALUE

        messages: list[dict[str, Any]] = []
        with self._call_cursor_context(stream.select, timestamp, options) as cursor:
            cursor = cast("dxapi_types.TickCursor", cursor)
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
            cursor = cast("dxapi_types.TickCursor", cursor)
            while len(messages) < limit and cursor.next():
                messages.append(self._normalize_message(cursor.getMessage()))

        return messages

    def _compile_query_tokens(self, query_text: str) -> list[Any]:
        return list[Any](self._require_db().compileQuery(query_text))

    def _ensure_dxapi(self) -> None:
        if dxapi is None:
            raise ConfigurationError(
                "Enterprise edition requires installing timebase-mcp[enterprise]"
            ) from _DXAPI_IMPORT_ERROR
