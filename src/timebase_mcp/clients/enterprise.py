from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, cast

from timebase_mcp.auth.token_verifier import decode_claims_unverified
from timebase_mcp.clients.base import TimeBaseClient
from timebase_mcp.constants import APP_NAME
from timebase_mcp.errors import (
    ConfigurationError,
    StreamNotFoundError,
    TimeBaseConnectionError,
)
from timebase_mcp.instance import TimeBaseInstanceConfig
from timebase_mcp.auth.oauth2 import (
    OAuth2AccessTokenProvider,
    OAuth2ClientCredentialsConfig,
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
    def __init__(
        self,
        settings: TimeBaseInstanceConfig,
        *,
        read_only: bool = False,
    ) -> None:
        super().__init__(settings, read_only=read_only)
        self._db: dxapi_types.TickDb | None = None
        self._oauth2_provider: OAuth2AccessTokenProvider | None = None
        self._token_provider: OAuth2AccessTokenProvider | None = None

    def set_token_provider(self, provider: OAuth2AccessTokenProvider) -> None:
        """Provide the interactive-login token source for ``interactive`` mode."""
        self._token_provider = provider

    def open(self) -> dxapi_types.TickDb:
        if self._db is not None and self._db.isOpen():
            return self._db

        self._ensure_dxapi()
        assert dxapi is not None

        try:
            username, access_token = self._resolve_token_credentials()
            if username is not None and access_token is not None:
                db = dxapi.TickDb.createFromUrl(
                    self._config.tb_url,
                    username,
                    access_token,
                )
            else:
                password = None
                if self._config.tb_password is not None:
                    password = self._config.tb_password.get_secret_value()

                if self._config.tb_username is None and password is None:
                    db = dxapi.TickDb.createFromUrl(self._config.tb_url)
                else:
                    basic_username = self._config.tb_username
                    assert basic_username is not None
                    assert password is not None
                    db = dxapi.TickDb.createFromUrl(
                        self._config.tb_url, basic_username, password
                    )

            db.setApplicationName(APP_NAME)
            db.open(self._read_only)
        except TimeBaseConnectionError:
            raise
        except Exception as exc:
            hint = self._connection_error_hint(exc)
            raise TimeBaseConnectionError(
                f"Failed to connect to TimeBase at '{self._config.tb_url}': {exc}{hint}"
            ) from exc

        logger.info(
            "Connected to TimeBase via enterprise client at %s (read-only=%s)",
            self._config.tb_url,
            self._read_only,
        )
        self._db = db
        return db

    def _resolve_token_credentials(self) -> tuple[str | None, str | None]:
        """Return `(username, access_token)` for token-based outbound auth.

        Returns ``(None, None)`` when token auth does not apply, so the caller
        falls back to basic / anonymous connection.
        """
        config = self._config

        if config.access_token is not None:
            username = self._username_for_token(
                config.access_token,
                config.access_token_username or config.tb_username,
            )
            logger.debug(
                "Connecting to TimeBase at %s with forwarded caller identity.",
                config.tb_url,
            )
            return username, config.access_token

        if config.auth_mode == "interactive":
            token = self._interactive_token()
            username = self._username_for_token(token, config.tb_username)
            return username, token

        oauth2_config = config.oauth2_config
        if oauth2_config is not None:
            username = config.tb_username
            assert username is not None
            return username, self._client_credentials_token(oauth2_config)

        return None, None

    def _client_credentials_token(
        self,
        oauth2_config: OAuth2ClientCredentialsConfig,
    ) -> str:
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
                f"'{self._config.tb_url}': {exc}"
            ) from exc

        logger.debug(
            "Obtained OAuth2 access token for TimeBase at %s using client ID %s",
            self._config.tb_url,
            oauth2_config.client_id,
        )
        return access_token

    def _interactive_token(self) -> str:
        if self._token_provider is None:
            raise TimeBaseConnectionError(
                "Interactive login is not configured for TimeBase at "
                f"'{self._config.tb_url}'."
            )

        try:
            return self._token_provider.get_access_token()
        except (ValueError, PermissionError, ConnectionError) as exc:
            raise TimeBaseConnectionError(
                "Interactive login to TimeBase at "
                f"'{self._config.tb_url}' failed: {exc}"
            ) from exc

    @staticmethod
    def _username_for_token(token: str, explicit_username: str | None) -> str:
        if explicit_username is not None:
            return explicit_username

        claims = decode_claims_unverified(token)
        for claim_name in ("preferred_username", "username", "upn", "email", "sub"):
            value = claims.get(claim_name)
            if isinstance(value, str) and value:
                return value

        return "oauth"

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
                "set DXAPI_SSL_TERMINATION=true or let local auto auth discover "
                "the HTTPS /tb/oauthinfo endpoint before connecting."
            )

        if "wrong username or password" in normalized and self._config.auth_mode in (
            "auto",
            "none",
        ):
            hints.append(
                "The server looks protected but MCP connected without credentials. "
                "For local MCP, use URL-only auto auth or set "
                "TIMEBASE_AUTH_MODE=interactive. For remote MCP, configure "
                "forward_identity or a service account."
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
