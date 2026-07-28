from __future__ import annotations

import logging
from typing import Any

import httpx2

from timebase_mcp.auth.outbound import (
    build_http_auth_headers,
    resolve_auto_auth_config,
)
from timebase_mcp.clients.http.urls import (
    build_tb_url,
    derive_http_base_urls,
    http_base_url_candidates,
)
from timebase_mcp.config.env import dxapi_ssl_trust_all_enabled
from timebase_mcp.runtime.instance import TimeBaseInstanceRuntime

logger = logging.getLogger(__name__)

HTTP_DISCOVERY_TIMEOUT_SECONDS = 3.0
HTTP_PING_TIMEOUT_SECONDS = 2.0

_trust_all_warning_emitted = False


def tls_verify() -> bool:
    """Return the TLS verification flag for TimeBase HTTP calls."""
    if not dxapi_ssl_trust_all_enabled():
        return True

    global _trust_all_warning_emitted
    if not _trust_all_warning_emitted:
        logger.warning(
            "DXAPI_SSL_TRUST_ALL=true disables TLS certificate verification for "
            "TimeBase HTTP calls. This weakens endpoint trust."
        )
        _trust_all_warning_emitted = True
    return False


def get_http_base_url(
    instance: TimeBaseInstanceRuntime,
    *,
    client: httpx2.Client | None = None,
    timeout: float = HTTP_PING_TIMEOUT_SECONDS,
    force_refresh: bool = False,
    exclude_http_base_url: str | None = None,
) -> str | None:
    """Return the first reachable TimeBase HTTP base URL, checked via ping endpoint."""
    if (
        instance.resolved_http_base_url is not None
        and not force_refresh
        and instance.resolved_http_base_url != exclude_http_base_url
    ):
        return instance.resolved_http_base_url

    config = instance.config
    candidates = (
        http_base_url_candidates(config.http_base_url)
        if config.http_base_url
        else derive_http_base_urls(config.tb_url)
    )
    for candidate in candidates:
        if candidate == exclude_http_base_url:
            continue
        if _is_reachable(candidate, "/ping", client=client, timeout=timeout):
            instance.resolved_http_base_url = candidate
            return candidate
    instance.clear_http_base_url()
    return None


def timebase_http_request(
    instance: TimeBaseInstanceRuntime,
    endpoint: str,
    *,
    method: str = "GET",
    client: httpx2.Client | None = None,
    timeout: float = HTTP_DISCOVERY_TIMEOUT_SECONDS,
    auth: bool = True,
    **kwargs: Any,
) -> httpx2.Response:
    """Make a request to TimeBase's HTTP API."""
    failed_base_url = instance.resolved_http_base_url
    try:
        response = _timebase_http_request(
            instance,
            endpoint,
            method=method,
            client=client,
            timeout=timeout,
            auth=auth,
            **kwargs,
        )
    except httpx2.HTTPError:
        instance.clear_http_base_url()
        return _timebase_http_request(
            instance,
            endpoint,
            method=method,
            client=client,
            timeout=timeout,
            exclude_http_base_url=failed_base_url,
            auth=auth,
            **kwargs,
        )
    if response.status_code != 404:
        return response

    rediscovered_base_url = get_http_base_url(
        instance,
        client=client,
        timeout=timeout,
        force_refresh=True,
    )
    if rediscovered_base_url is None or rediscovered_base_url == failed_base_url:
        return response

    return _timebase_http_request(
        instance,
        endpoint,
        method=method,
        client=client,
        timeout=timeout,
        auth=auth,
        **kwargs,
    )


def _timebase_http_request(
    instance: TimeBaseInstanceRuntime,
    endpoint: str,
    *,
    method: str,
    client: httpx2.Client | None,
    timeout: float,
    exclude_http_base_url: str | None = None,
    auth: bool = True,
    **kwargs: Any,
) -> httpx2.Response:
    http_base_url = get_http_base_url(
        instance,
        client=client,
        timeout=timeout,
        exclude_http_base_url=exclude_http_base_url,
    )
    if http_base_url is None:
        raise httpx2.ConnectError(
            f"Cannot resolve TimeBase HTTP API URL for instance '{instance.key}'."
        )

    url = build_tb_url(http_base_url, endpoint)
    if auth:
        kwargs = _with_auth_headers(instance, kwargs)
    return _http_request(method, url, client=client, timeout=timeout, **kwargs)


def _with_auth_headers(
    instance: TimeBaseInstanceRuntime,
    kwargs: dict[str, Any],
) -> dict[str, Any]:
    resolve_auto_auth_config(instance, instance.config)
    auth_headers = build_http_auth_headers(instance)
    if not auth_headers:
        return kwargs

    headers = dict(kwargs.get("headers") or {})
    if not any(key.casefold() == "authorization" for key in headers):
        headers.update(auth_headers)

    updated_kwargs = dict(kwargs)
    updated_kwargs["headers"] = headers
    return updated_kwargs


def _http_request(
    method: str,
    url: str,
    *,
    client: httpx2.Client | None,
    timeout: float,
    **kwargs: Any,
) -> httpx2.Response:
    if client is not None:
        return client.request(method, url, timeout=timeout, **kwargs)
    return httpx2.request(
        method,
        url,
        timeout=timeout,
        verify=tls_verify(),
        **kwargs,
    )


def _is_reachable(
    http_base_url: str,
    endpoint: str,
    *,
    client: httpx2.Client | None,
    timeout: float,
) -> bool:
    url = build_tb_url(http_base_url, endpoint)
    try:
        response = _http_request(
            "GET",
            url,
            client=client,
            timeout=timeout,
        )
    except httpx2.HTTPError:
        return False
    return 200 <= response.status_code < 300 or response.status_code in (401, 403)
