from __future__ import annotations

import base64
import hashlib
import logging
import secrets
import sys
import threading
import time
import webbrowser
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

from timebase_mcp.auth.discovery import (
    InteractiveEndpoints,
    derive_http_base_urls,
    resolve_interactive_endpoints,
)
from timebase_mcp.auth.oauth2 import (
    TOKEN_REQUEST_TIMEOUT_SECONDS,
    OAuth2AccessTokenProvider,
    TokenResponse,
    parse_json_token_response,
    parse_token_response,
    token_has_expired,
)
from timebase_mcp.errors import ConfigurationError

if TYPE_CHECKING:
    from timebase_mcp.instance import TimeBaseInstanceConfig

logger = logging.getLogger(__name__)

_DEFAULT_LOGIN_TIMEOUT_SECONDS = 300.0
_DEFAULT_REDIRECT_PATH = "/"
_WILDCARD_BIND_HOSTS = frozenset({"0.0.0.0", "::", "0:0:0:0:0:0:0:1"})


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _redirect_bind_host(host: str) -> str:
    """Map wildcard MCP bind hosts to a concrete loopback address.

    Preserves ``localhost`` and ``127.0.0.1`` as configured so the redirect URI
    matches IdP registrations exactly.
    """
    normalized = host.strip().casefold()
    if normalized in _WILDCARD_BIND_HOSTS:
        return "127.0.0.1"
    return host.strip()


def resolve_interactive_redirect_uri(*, host: str, port: int) -> str:
    """Build the OAuth redirect URI used for stdio interactive login.

    Derives ``http://{MCP_HOST}:{MCP_PORT}/``. Only wildcard bind hosts such as
    ``0.0.0.0`` are rewritten to ``127.0.0.1``; ``localhost`` is kept as-is.
    """
    redirect_host = _redirect_bind_host(host)
    return f"http://{redirect_host}:{port}/"


def _parse_redirect_uri(redirect_uri: str) -> tuple[str, int, str]:
    parsed = urlparse(redirect_uri)
    if parsed.scheme != "http":
        raise ConfigurationError(
            "Interactive OAuth redirect URI must use the http scheme for loopback "
            f"login (got {redirect_uri!r})."
        )

    host = parsed.hostname
    if host is None or not host:
        raise ConfigurationError(
            f"Interactive OAuth redirect URI is missing a host: {redirect_uri!r}."
        )

    port = parsed.port if parsed.port is not None else 80
    path = parsed.path or "/"
    if not path.startswith("/"):
        path = f"/{path}"

    return host, port, f"http://{host}:{port}{path}"


class _CallbackHTTPServer(HTTPServer):
    expected_path: str
    received_query: dict[str, list[str]] | None


class _CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        server = cast(_CallbackHTTPServer, self.server)
        if urlparse(self.path).path != server.expected_path:
            self.send_response(404)
            self.end_headers()
            return

        query = parse_qs(urlparse(self.path).query)
        server.received_query = query

        success = "error" not in query and "code" in query
        message = (
            "Login complete. You can close this window and return to your client."
            if success
            else "Login failed. You can close this window."
        )
        body = f"<html><body><p>{message}</p></body></html>".encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        """Silence default stderr logging."""
        return


class InteractiveOAuthProvider(OAuth2AccessTokenProvider):
    """Outbound token source backed by an interactive OAuth login.

    Runs an authorization-code + PKCE flow via a loopback redirect, caches the
    access/refresh tokens, and refreshes silently when possible. Suitable for a
    local (stdio) MCP where the user can complete a browser login.
    """

    def __init__(
        self,
        *,
        discovery_base_url: str | tuple[str, ...] | None,
        client_id_override: str | None = None,
        scope_override: str | None = None,
        issuer_override: str | None = None,
        redirect_uri: str | None = None,
        login_timeout_seconds: float = _DEFAULT_LOGIN_TIMEOUT_SECONDS,
        monotonic: Callable[[], float] = time.monotonic,
        open_browser: Callable[[str], bool] = webbrowser.open,
    ) -> None:
        self._discovery_base_url = discovery_base_url
        self._client_id_override = client_id_override
        self._scope_override = scope_override
        self._issuer_override = issuer_override
        self._redirect_uri = redirect_uri
        self._login_timeout_seconds = login_timeout_seconds
        self._monotonic = monotonic
        self._open_browser = open_browser

        self._lock = threading.Lock()
        self._endpoints: InteractiveEndpoints | None = None
        self._access_token: str | None = None
        self._refresh_token: str | None = None
        self._expires_at_monotonic: float | None = None

    def get_access_token(self) -> str:
        with self._lock:
            if self._access_token is not None and not self._token_expired():
                return self._access_token

            if self._refresh_token is not None:
                try:
                    self._refresh()
                    if self._access_token is not None:
                        return self._access_token
                except (httpx.HTTPError, ValueError, PermissionError) as exc:
                    logger.info(
                        "Refreshing TimeBase token failed (%s); re-running login.",
                        exc,
                    )

            self._login()
            assert self._access_token is not None
            return self._access_token

    def _token_expired(self) -> bool:
        return token_has_expired(
            self._expires_at_monotonic,
            monotonic=self._monotonic,
        )

    def _get_endpoints(self) -> InteractiveEndpoints:
        if self._endpoints is None:
            self._endpoints = resolve_interactive_endpoints(
                discovery_base_url=self._discovery_base_url,
                issuer_override=self._issuer_override,
                client_id_override=self._client_id_override,
                scope_override=self._scope_override,
            )
        return self._endpoints

    def _login(self) -> None:
        endpoints = self._get_endpoints()
        code_verifier = _b64url(secrets.token_bytes(32))
        code_challenge = _b64url(hashlib.sha256(code_verifier.encode("ascii")).digest())
        state = secrets.token_urlsafe(16)

        redirect_uri = self._resolve_redirect_uri()
        bind_host, bind_port, redirect_uri = _parse_redirect_uri(redirect_uri)
        try:
            server = _CallbackHTTPServer((bind_host, bind_port), _CallbackHandler)
        except OSError as exc:
            raise ConnectionError(
                "Cannot bind the OAuth login callback listener on "
                f"{bind_host}:{bind_port}. Register {redirect_uri!r} with your IdP "
                "and ensure MCP_PORT is free for interactive login, or set MCP_HOST "
                "and MCP_PORT to a different loopback URI."
            ) from exc

        server.received_query = None
        server.expected_path = urlparse(redirect_uri).path

        authorize_url = (
            endpoints.authorization_endpoint
            + "?"
            + urlencode(
                {
                    "response_type": "code",
                    "client_id": endpoints.client_id,
                    "redirect_uri": redirect_uri,
                    "scope": endpoints.scope,
                    "state": state,
                    "code_challenge": code_challenge,
                    "code_challenge_method": "S256",
                }
            )
        )

        logger.info(
            "Starting interactive TimeBase login (redirect_uri=%s).", redirect_uri
        )
        print(
            "To authenticate with TimeBase, open this URL in your browser:\n"
            f"{authorize_url}\n"
            f"OAuth callback URI: {redirect_uri}",
            file=sys.stderr,
            flush=True,
        )
        try:
            self._open_browser(authorize_url)
        except Exception:
            logger.debug("Could not auto-open a browser for login.", exc_info=True)

        query = self._wait_for_callback(server)

        if "error" in query:
            raise PermissionError(
                self._first(query, "error_description")
                or self._first(query, "error")
                or "Interactive login was denied."
            )
        if self._first(query, "state") != state:
            raise PermissionError("OAuth state mismatch during interactive login.")

        code = self._first(query, "code")
        if not code:
            raise PermissionError("Authorization code missing from the login callback.")

        self._exchange_code(endpoints, code, code_verifier, redirect_uri)

    def _wait_for_callback(self, server: _CallbackHTTPServer) -> dict[str, list[str]]:
        deadline = self._monotonic() + self._login_timeout_seconds
        server.timeout = 1.0
        try:
            while server.received_query is None and self._monotonic() < deadline:
                server.handle_request()
        finally:
            server.server_close()

        query = server.received_query
        if query is None:
            raise ConnectionError("Timed out waiting for interactive login.")
        return query

    def _exchange_code(
        self,
        endpoints: InteractiveEndpoints,
        code: str,
        code_verifier: str,
        redirect_uri: str,
    ) -> None:
        token_response = self._post_token(
            endpoints.token_endpoint,
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "client_id": endpoints.client_id,
                "code_verifier": code_verifier,
            },
        )
        self._store_token(token_response)

    def _refresh(self) -> None:
        endpoints = self._get_endpoints()
        data = {
            "grant_type": "refresh_token",
            "refresh_token": self._refresh_token,
            "client_id": endpoints.client_id,
        }
        if endpoints.scope:
            data["scope"] = endpoints.scope
        self._store_token(self._post_token(endpoints.token_endpoint, data))

    def _post_token(self, token_endpoint: str, data: dict[str, Any]) -> TokenResponse:
        try:
            response = httpx.post(
                token_endpoint,
                data=data,
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                timeout=TOKEN_REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (400, 401, 403):
                raise PermissionError(
                    f"OAuth token request rejected: {exc.response.text}"
                ) from exc
            raise ConnectionError(f"OAuth token request failed: {exc}") from exc
        except httpx.HTTPError as exc:
            raise ConnectionError(f"OAuth token request failed: {exc}") from exc

        payload = parse_json_token_response(response.text)

        return parse_token_response(
            payload,
            monotonic=self._monotonic,
            access_token_error="OAuth token response did not include an access_token.",
        )

    def _store_token(self, token_response: TokenResponse | dict[str, Any]) -> None:
        if isinstance(token_response, dict):
            token_response = parse_token_response(
                token_response,
                monotonic=self._monotonic,
                access_token_error="OAuth token response did not include an access_token.",
            )

        self._access_token = token_response.access_token
        if token_response.refresh_token is not None:
            self._refresh_token = token_response.refresh_token
        self._expires_at_monotonic = token_response.expires_at_monotonic

    def _resolve_redirect_uri(self) -> str:
        if self._redirect_uri is not None:
            return self._redirect_uri

        raise ConfigurationError(
            "Interactive OAuth redirect URI is not configured. Build the provider "
            "through build_interactive_provider() or pass redirect_uri explicitly."
        )

    @staticmethod
    def _first(query: dict[str, list[str]], key: str) -> str | None:
        values = query.get(key)
        if not values:
            return None
        return values[0]


def build_interactive_provider(
    config: "TimeBaseInstanceConfig",
    *,
    redirect_uri: str | None = None,
) -> OAuth2AccessTokenProvider:
    discovery_base_url = config.http_base_url or derive_http_base_urls(config.tb_url)
    return InteractiveOAuthProvider(
        discovery_base_url=discovery_base_url,
        client_id_override=config.tb_oauth2_client_id,
        scope_override=config.tb_oauth2_scope,
        redirect_uri=redirect_uri,
    )
