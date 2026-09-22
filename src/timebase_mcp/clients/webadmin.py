from __future__ import annotations

import base64
import hashlib
import hmac
import time
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

import httpx2

from timebase_mcp.auth.oauth2 import (
    OAuth2ClientCredentialsConfig,
    OAuth2ClientCredentialsProvider,
    OAuth2PasswordConfig,
    OAuth2PasswordProvider,
)
from timebase_mcp.auth.webadmin_oauth import (
    WEBADMIN_CLIENT_ID,
    WEBADMIN_CLIENT_SECRET,
    WEBADMIN_PASSWORD_SCOPE,
    WebAdminBearerFileProvider,
    WebAdminInteractiveProvider,
)
from timebase_mcp.auth.webadmin_session import WebAdminSession
from timebase_mcp.clients.http.transport import http_request
from timebase_mcp.clients.http.urls import build_http_url
from timebase_mcp.errors import TimeBaseOperationError
from timebase_mcp.runtime.instance import TimeBaseInstanceRuntime

MAX_WEBADMIN_RESPONSE_BYTES = 128 * 1024
_WEBADMIN_PASSWORD_GRANT_PROVIDER = "BUILT_IN_OAUTH"
_KNOWN_WEBADMIN_PROVIDER_TYPES = frozenset(
    {"BUILT_IN_OAUTH", "EXTERNAL_OAUTH", "SSO", "SSO_BFF"}
)


def get_webadmin_payload(
    instance: TimeBaseInstanceRuntime,
    endpoint: str,
    *,
    authenticated: bool = True,
) -> object:
    if authenticated and instance.config.webadmin.auth.private_key_file is not None:
        # Keep allocation and network completion ordered for this session.
        with instance.webadmin_auth_lock:
            return _get_webadmin_payload(
                instance, endpoint, authenticated=authenticated
            )
    return _get_webadmin_payload(instance, endpoint, authenticated=authenticated)


def _get_webadmin_payload(
    instance: TimeBaseInstanceRuntime, endpoint: str, *, authenticated: bool
) -> object:
    config = instance.config.webadmin
    auth = config.auth
    base_url = config.url
    if base_url is None:
        raise TimeBaseOperationError(
            f"TimeBase instance '{instance.key}' has no WebAdmin URL configured."
        )

    headers = None
    request_provider = None
    request_token_fingerprint = None
    if authenticated:
        if auth.private_key_file is not None:
            if (
                instance.webadmin_session is None
                or time.monotonic() >= instance.webadmin_session.expires_at
            ):

                def post(suffix: str, body: dict[str, str]) -> dict[str, object]:
                    response = http_request(
                        "POST",
                        build_http_url(
                            base_url,
                            (auth.session_login_root or "/session/login") + suffix,
                        ),
                        json=body,
                        follow_redirects=False,
                        max_response_bytes=32768,
                    )
                    if response.status_code != 200:
                        raise TimeBaseOperationError(
                            f"WebAdmin session login failed with HTTP {response.status_code}."
                        )
                    value = response.json()
                    if not isinstance(value, dict):
                        raise TypeError("Expected session object")
                    return value

                try:
                    instance.webadmin_session = WebAdminSession.acquire(
                        auth.api_key or "",
                        auth.private_key_file,
                        post,
                    )
                except (httpx2.HTTPError, ValueError) as exc:
                    raise TimeBaseOperationError(
                        "WebAdmin session endpoint unavailable or invalid."
                    ) from exc
            headers = instance.webadmin_session.headers(_webadmin_get_payload(endpoint))
        elif auth.api_key is not None:
            headers = _webadmin_api_key_headers(instance, endpoint)
        else:
            with instance.webadmin_auth_lock:
                headers = _locked_webadmin_auth_headers(instance)
                request_provider = instance.webadmin_provider
                request_token_fingerprint = hashlib.sha256(
                    headers["Authorization"].encode("utf-8")
                ).digest()
                instance.webadmin_token_fingerprint = request_token_fingerprint
    try:
        response = http_request(
            "GET",
            build_http_url(base_url, endpoint),
            headers=headers,
            follow_redirects=False,
            max_response_bytes=MAX_WEBADMIN_RESPONSE_BYTES,
        )
    except ValueError as exc:
        raise TimeBaseOperationError(
            f"WebAdmin endpoint {endpoint} exceeded the 128 KiB response limit."
        ) from exc
    except httpx2.HTTPError as exc:
        raise TimeBaseOperationError(
            f"WebAdmin endpoint {base_url} is unavailable ({type(exc).__name__})."
        ) from exc
    if authenticated and auth.private_key_file is not None:
        if response.status_code in {400, 401}:
            instance.webadmin_session = None
        elif instance.webadmin_session is not None:
            instance.webadmin_session.expires_at = (
                time.monotonic() + instance.webadmin_session.idle_seconds * 0.9
            )
    elif authenticated and response.status_code == 401:
        with instance.webadmin_auth_lock:
            if (
                instance.webadmin_provider is request_provider
                and instance.webadmin_token_fingerprint == request_token_fingerprint
            ):
                instance.webadmin_provider = None
                instance.webadmin_token_fingerprint = None
    _raise_for_webadmin_response(response, endpoint=endpoint)
    try:
        return response.json()
    except ValueError as exc:
        raise TimeBaseOperationError(
            f"Expected JSON response from WebAdmin endpoint {endpoint}."
        ) from exc


def get_webadmin_json(
    instance: TimeBaseInstanceRuntime,
    endpoint: str,
    *,
    authenticated: bool = True,
) -> dict[str, Any]:
    payload = get_webadmin_payload(
        instance,
        endpoint,
        authenticated=authenticated,
    )
    if not isinstance(payload, dict):
        raise TimeBaseOperationError(
            f"Unexpected response from WebAdmin endpoint {endpoint}."
        )
    return payload


def _webadmin_api_key_headers(
    instance: TimeBaseInstanceRuntime, endpoint: str
) -> dict[str, str]:
    config = instance.config.webadmin
    auth = config.auth
    if auth.api_key is None or auth.api_secret is None:
        raise TimeBaseOperationError("WebAdmin API key and API secret are required.")
    payload = _webadmin_get_payload(endpoint)
    signature = base64.b64encode(
        hmac.new(
            auth.api_secret.get_secret_value().encode("utf-8"),
            payload.encode("utf-8"),
            hashlib.sha384,
        ).digest()
    ).decode("ascii")
    return {"X-Deltix-ApiKey": auth.api_key, "X-Deltix-Signature": signature}


def _webadmin_get_payload(endpoint: str) -> str:
    # The servlet path excludes the deployment context/proxy prefix in webadmin_url.
    route = urlsplit(endpoint)
    parameters = parse_qs(route.query, keep_blank_values=True, errors="strict")
    java_order = lambda value: value.encode("utf-16-be")
    query = "&".join(
        f"{name.lower()}={value}"
        for name in sorted(parameters, key=java_order)
        for value in sorted(parameters[name], key=java_order)
    )
    return "GET" + unquote(route.path, errors="strict").lower() + query


def _locked_webadmin_auth_headers(instance: TimeBaseInstanceRuntime) -> dict[str, str]:
    config = instance.config.webadmin
    auth = config.auth
    if auth.mode != "password":
        return _webadmin_oauth_headers(instance)
    if auth.username is None or auth.password is None:
        raise TimeBaseOperationError(
            f"TimeBase instance '{instance.key}' requires "
            "TIMEBASE_WEBADMIN_USERNAME and TIMEBASE_WEBADMIN_PASSWORD "
            "for WebAdmin authentication."
        )

    if instance.webadmin_provider is None:
        auth_info = get_webadmin_json(
            instance,
            "/api/v0/authInfo",
            authenticated=False,
        )
        provider_type = auth_info.get("provider_type")
        if provider_type != _WEBADMIN_PASSWORD_GRANT_PROVIDER:
            provider_description = (
                provider_type
                if isinstance(provider_type, str)
                and provider_type in _KNOWN_WEBADMIN_PROVIDER_TYPES
                else "unknown"
            )
            raise TimeBaseOperationError(
                "WebAdmin password authentication supports BUILT_IN_OAUTH only; "
                f"the server reports {provider_description}."
            )
        token_endpoint = auth_info.get("token_endpoint")
        if not isinstance(token_endpoint, str) or not token_endpoint:
            raise TimeBaseOperationError(
                "WebAdmin authInfo did not include a token_endpoint."
            )
        oauth_server = auth_info.get("oauth_server")
        token_base_url = oauth_server if isinstance(oauth_server, str) else config.url
        assert token_base_url is not None
        assert config.url is not None
        token_url = build_http_url(token_base_url, token_endpoint)
        target = urlsplit(token_url)
        configured = urlsplit(config.url)
        if (
            target.scheme not in {"http", "https"}
            or target.username is not None
            or target.password is not None
            or target.fragment
            or (
                target.scheme,
                target.hostname,
                target.port or (443 if target.scheme == "https" else 80),
            )
            != (
                configured.scheme,
                configured.hostname,
                configured.port or (443 if configured.scheme == "https" else 80),
            )
            or "://" in token_endpoint
            or token_endpoint.startswith("//")
        ):
            raise TimeBaseOperationError(
                "WebAdmin built-in token endpoint must use the same origin as the configured WebAdmin URL."
            )
        instance.webadmin_provider = OAuth2PasswordProvider(
            OAuth2PasswordConfig(
                token_url=token_url,
                username=auth.username,
                password=auth.password.get_secret_value(),
                scope=WEBADMIN_PASSWORD_SCOPE,
                client_id=auth.client_id or WEBADMIN_CLIENT_ID,
                client_secret=(
                    auth.client_secret.get_secret_value()
                    if auth.client_secret is not None
                    else WEBADMIN_CLIENT_SECRET
                ),
            )
        )

    try:
        token = instance.webadmin_provider.get_access_token()
    except PermissionError as exc:
        raise TimeBaseOperationError(
            "WebAdmin authentication failed: token request was rejected. Check user and OAuth client credentials."
        ) from exc
    except (ConnectionError, ValueError) as exc:
        raise TimeBaseOperationError(
            "WebAdmin authentication failed: token endpoint unavailable or returned an invalid response."
        ) from exc
    return {"Authorization": f"Bearer {token}"}


def _webadmin_oauth_headers(instance: TimeBaseInstanceRuntime) -> dict[str, str]:
    config = instance.config.webadmin
    auth = config.auth
    if auth.mode == "interactive" and instance.runtime_is_http_transport:
        raise TimeBaseOperationError(
            "WebAdmin browser login requires local stdio MCP. Use a service identity or managed token file for HTTP MCP."
        )
    if instance.webadmin_provider is None:
        discovery = get_webadmin_json(instance, "/api/v0/authInfo", authenticated=False)
        if discovery.get("provider_type") not in _KNOWN_WEBADMIN_PROVIDER_TYPES:
            raise TimeBaseOperationError("Unknown WebAdmin authentication provider.")
        if auth.mode == "interactive":
            expected = (auth.issuer_url or "").rstrip(
                "/"
            ) + "/.well-known/openid-configuration"
            advertised = discovery.get("config_url")
            optional_discovery_missing = (
                discovery.get("provider_type") in {"SSO_BFF", "EXTERNAL_OAUTH"}
                and advertised is None
            )
            if advertised != expected and not optional_discovery_missing:
                raise TimeBaseOperationError(
                    "WebAdmin discovery does not match the configured trusted issuer."
                )
            instance.webadmin_provider = WebAdminInteractiveProvider(
                resource_name="WebAdmin",
                issuer_override=auth.issuer_url,
                client_id_override=auth.client_id,
                scope_override=auth.scope,
                redirect_uri=auth.redirect_uri,
            )
        elif auth.mode == "client_credentials":
            assert auth.token_url and auth.client_id and auth.client_secret
            instance.webadmin_provider = OAuth2ClientCredentialsProvider(
                OAuth2ClientCredentialsConfig(
                    token_url=auth.token_url,
                    client_id=auth.client_id,
                    client_secret=auth.client_secret.get_secret_value(),
                    scope=auth.scope,
                )
            )
        elif auth.mode == "bearer_file":
            assert auth.token_file
            instance.webadmin_provider = WebAdminBearerFileProvider(auth.token_file)
        else:
            raise TimeBaseOperationError("Unknown WebAdmin auth mode.")
    try:
        token = instance.webadmin_provider.get_access_token()
    except (PermissionError, ConnectionError, ValueError) as exc:
        raise TimeBaseOperationError(
            "WebAdmin OAuth authentication failed; check identity configuration and login availability."
        ) from exc
    if not token or any(c.isspace() or ord(c) < 33 or ord(c) > 126 for c in token):
        raise TimeBaseOperationError("WebAdmin OAuth returned an invalid bearer token.")
    return {"Authorization": f"Bearer {token}"}


def _raise_for_webadmin_response(
    response: httpx2.Response,
    *,
    endpoint: str,
) -> None:
    if response.status_code == 401:
        raise TimeBaseOperationError(
            f"WebAdmin endpoint {endpoint} rejected authentication (HTTP 401)."
        )
    if response.status_code == 403:
        raise TimeBaseOperationError(
            f"WebAdmin endpoint {endpoint} denied permission (HTTP 403)."
        )
    if response.status_code == 404:
        raise TimeBaseOperationError(f"WebAdmin endpoint {endpoint} is not available.")
    if response.status_code != 200:
        raise TimeBaseOperationError(
            f"WebAdmin endpoint {endpoint} returned HTTP {response.status_code}; expected HTTP 200."
        )
