from __future__ import annotations

from pathlib import Path

import httpx2
from typing_extensions import override

from timebase_mcp.auth.discovery import InteractiveEndpoints
from timebase_mcp.auth.interactive import InteractiveOAuthProvider
from timebase_mcp.clients.http.transport import http_request
from timebase_mcp.config.webadmin import trusted_https_url

WEBADMIN_PASSWORD_SCOPE = "trust"
WEBADMIN_CLIENT_ID = "web"
WEBADMIN_CLIENT_SECRET = "secret"


class WebAdminBearerFileProvider:
    def __init__(self, path: str) -> None:
        self._path = path

    def get_access_token(self) -> str:
        try:
            with Path(self._path).open("rb") as stream:
                raw = stream.read(32769)
            token = raw.decode("ascii").strip()
        except (OSError, UnicodeError) as exc:
            raise ValueError("WebAdmin token file is unreadable or invalid.") from exc
        if (
            len(raw) > 32768
            or not token
            or any(c.isspace() or ord(c) < 33 or ord(c) > 126 for c in token)
        ):
            raise ValueError(
                "WebAdmin token file must contain one bounded bearer token."
            )
        return token


class WebAdminInteractiveProvider(InteractiveOAuthProvider):
    """PKCE with explicitly trusted OIDC metadata and bounded, redacted transport."""

    @override
    def _get_endpoints(self) -> InteractiveEndpoints:
        if self._endpoints is not None:
            return self._endpoints
        issuer = self._issuer_override
        assert issuer is not None
        origin = trusted_https_url(issuer)
        try:
            with httpx2.Client(verify=True) as client:
                response = http_request(
                    "GET",
                    issuer.rstrip("/") + "/.well-known/openid-configuration",
                    client=client,
                    timeout=15,
                    follow_redirects=False,
                    max_response_bytes=32768,
                )
            if response.status_code != 200:
                raise ValueError("WebAdmin OIDC discovery was rejected.")
            metadata = response.json()
            if not isinstance(metadata, dict) or metadata.get("issuer") != issuer:
                raise ValueError(
                    "WebAdmin OIDC issuer does not match the configured issuer."
                )
            endpoints = []
            for name in ("authorization_endpoint", "token_endpoint"):
                endpoint = metadata.get(name)
                if (
                    not isinstance(endpoint, str)
                    or trusted_https_url(endpoint) != origin
                ):
                    raise ValueError(
                        "WebAdmin OIDC endpoints must share the trusted issuer origin."
                    )
                endpoints.append(endpoint)
        except httpx2.HTTPError as exc:
            raise ConnectionError("WebAdmin OIDC discovery unavailable.") from exc
        self._endpoints = InteractiveEndpoints(
            endpoints[0],
            endpoints[1],
            self._client_id_override or "",
            self._scope_override or "",
        )
        return self._endpoints
