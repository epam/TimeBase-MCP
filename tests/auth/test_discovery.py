from __future__ import annotations

import logging

import httpx2
import pytest

from timebase_mcp.auth.discovery import (
    fetch_oauthinfo,
    resolve_interactive_endpoints,
)
from timebase_mcp.clients.http.transport import timebase_http_request
from timebase_mcp.config.env import DXAPI_SSL_TERMINATION_ENV
from timebase_mcp.errors import ConfigurationError

from tests.auth.helpers import (
    DiscoveryResponse,
    timebase_oauthinfo_payload,
    http_instance,
)


def test_fetch_oauthinfo_parses_timebase_application_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance = http_instance()

    def handler(request: httpx2.Request) -> httpx2.Response:
        if str(request.url) == "https://tb.example.com:8011/tb/ping":
            return httpx2.Response(200)
        if str(request.url) == "https://tb.example.com:8011/tb/oauthinfo":
            return httpx2.Response(200, json=timebase_oauthinfo_payload())
        raise AssertionError(f"unexpected URL: {request.url}")

    with httpx2.Client(transport=httpx2.MockTransport(handler)) as client:
        monkeypatch.setattr(
            "timebase_mcp.auth.discovery.timebase_http_request",
            lambda instance, endpoint, **kwargs: timebase_http_request(
                instance,
                endpoint,
                client=client,
                **kwargs,
            ),
        )
        info = fetch_oauthinfo(instance)

    assert info.issuer == "https://login.microsoftonline.com/tenant/v2.0"
    assert info.client_id == "application-client"
    assert info.scope == "api://api-id/app openid profile offline_access"
    assert info.discovery_base_url == "https://tb.example.com:8011"


def test_fetch_oauthinfo_uses_single_clientid_without_app(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance = http_instance()

    monkeypatch.setattr(
        "timebase_mcp.auth.discovery.timebase_http_request",
        lambda _instance, _endpoint, **_kwargs: httpx2.Response(
            200,
            json={
                "issuer": "https://idp.example",
                "clientid": [{"name": "single-client"}],
                "scopes": [{"scope": "openid profile"}],
            },
        ),
    )

    info = fetch_oauthinfo(instance)

    assert info.client_id == "single-client"
    assert info.scope == "openid profile"


def test_fetch_oauthinfo_allows_empty_payload_when_auth_not_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance = http_instance()

    monkeypatch.setattr(
        "timebase_mcp.auth.discovery.timebase_http_request",
        lambda _instance, _endpoint, **_kwargs: httpx2.Response(
            200,
            headers={"content-type": "text/plain"},
            content=b"",
        ),
    )

    info = fetch_oauthinfo(instance)

    assert info.issuer is None
    assert info.client_id is None
    assert info.scope is None


def test_fetch_oauthinfo_raises_configuration_error_for_non_empty_invalid_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance = http_instance()

    monkeypatch.setattr(
        "timebase_mcp.auth.discovery.timebase_http_request",
        lambda _instance, _endpoint, **_kwargs: httpx2.Response(
            200,
            headers={"content-type": "text/plain"},
            content=b"not-json",
        ),
    )

    with pytest.raises(ConfigurationError, match="Expected JSON response"):
        fetch_oauthinfo(instance)


def test_resolve_interactive_endpoints_tries_https_candidate_and_trusts_all(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv(DXAPI_SSL_TERMINATION_ENV, "true")
    monkeypatch.setenv("DXAPI_SSL_TRUST_ALL", "true")
    instance = http_instance(http_base_url=None)
    calls: list[tuple[str, bool]] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        url = str(request.url)
        if url == "https://tb.example.com:8011/tb/ping":
            return httpx2.Response(200)
        if url == "https://tb.example.com:8011/tb/oauthinfo":
            return httpx2.Response(200, json=timebase_oauthinfo_payload())
        raise AssertionError(f"unexpected URL: {url}")

    def fake_get(url: str, *, timeout: float, verify: bool) -> DiscoveryResponse:
        calls.append((url, verify))
        if (
            url
            == "https://login.microsoftonline.com/tenant/v2.0/.well-known/openid-configuration"
        ):
            return DiscoveryResponse(
                {
                    "authorization_endpoint": "https://login.example/auth",
                    "token_endpoint": "https://login.example/token",
                    "jwks_uri": "https://login.example/jwks",
                }
            )
        raise AssertionError(f"unexpected URL: {url}")

    monkeypatch.setattr("timebase_mcp.auth.discovery.httpx2.get", fake_get)

    with (
        httpx2.Client(transport=httpx2.MockTransport(handler)) as client,
        caplog.at_level(logging.WARNING),
    ):
        monkeypatch.setattr(
            "timebase_mcp.clients.http.transport.httpx2.request",
            lambda method, url, *, timeout, verify, **kwargs: client.request(
                method,
                url,
                timeout=timeout,
                **kwargs,
            ),
        )
        endpoints = resolve_interactive_endpoints(
            instance=instance,
            issuer_override=None,
            client_id_override=None,
            scope_override=None,
        )

    assert endpoints.authorization_endpoint == "https://login.example/auth"
    assert endpoints.token_endpoint == "https://login.example/token"
    assert endpoints.client_id == "application-client"
    assert endpoints.scope == "api://api-id/app openid profile offline_access"
    assert endpoints.discovery_base_url == "https://tb.example.com:8011"
    assert calls == [
        (
            "https://login.microsoftonline.com/tenant/v2.0/.well-known/openid-configuration",
            False,
        ),
    ]
    assert caplog.text.count("DXAPI_SSL_TRUST_ALL=true disables TLS") == 1


def test_trust_all_warning_emits_once_for_multiple_discovery_calls(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv("DXAPI_SSL_TRUST_ALL", "true")
    instance = http_instance()

    def fake_request(method: str, url: str, *, timeout: float, verify: bool, **_kwargs):
        assert verify is False
        if url == "https://tb.example.com:8011/tb/ping":
            return httpx2.Response(200)
        if url == "https://tb.example.com:8011/tb/oauthinfo":
            return httpx2.Response(200, json=timebase_oauthinfo_payload())
        raise AssertionError(f"unexpected URL: {url}")

    monkeypatch.setattr(
        "timebase_mcp.clients.http.transport.httpx2.request", fake_request
    )

    with caplog.at_level(logging.WARNING):
        fetch_oauthinfo(instance)
        fetch_oauthinfo(instance)

    assert caplog.text.count("DXAPI_SSL_TRUST_ALL=true disables TLS") == 1


def test_trust_all_warning_not_emitted_when_verification_enabled(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.delenv("DXAPI_SSL_TRUST_ALL", raising=False)
    instance = http_instance()

    def fake_request(method: str, url: str, *, timeout: float, verify: bool, **_kwargs):
        assert verify is True
        if url == "https://tb.example.com:8011/tb/ping":
            return httpx2.Response(200)
        if url == "https://tb.example.com:8011/tb/oauthinfo":
            return httpx2.Response(200, json=timebase_oauthinfo_payload())
        raise AssertionError(f"unexpected URL: {url}")

    monkeypatch.setattr(
        "timebase_mcp.clients.http.transport.httpx2.request", fake_request
    )

    with caplog.at_level(logging.WARNING):
        fetch_oauthinfo(instance)

    assert "DXAPI_SSL_TRUST_ALL=true disables TLS" not in caplog.text
