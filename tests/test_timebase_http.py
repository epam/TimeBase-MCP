from __future__ import annotations

from base64 import b64encode

import httpx
import pytest
from mcp.server.auth.middleware.auth_context import auth_context_var
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
from mcp.server.auth.provider import AccessToken
from pydantic import SecretStr

from timebase_mcp.clients.http.transport import (
    get_http_base_url,
    timebase_http_request,
)
from timebase_mcp.clients.http.urls import (
    build_tb_url,
    derive_http_base_urls,
    http_base_url_candidates,
)
from timebase_mcp.runtime.instance import (
    TimeBaseInstanceConfig,
    TimeBaseInstanceRuntime,
)


def _http_instance(
    *,
    tb_url: str = "dxtick://tb.example.com:8011",
    http_base_url: str | None = "https://tb.example.com:8011",
) -> TimeBaseInstanceRuntime:
    return TimeBaseInstanceRuntime(
        key="default",
        config=TimeBaseInstanceConfig(
            tb_url=tb_url,
            http_base_url=http_base_url,
        ),
    )


class _StaticTokenProvider:
    def __init__(self, token: str) -> None:
        self.token = token
        self.calls = 0

    def get_access_token(self) -> str:
        self.calls += 1
        return self.token


def test_derive_http_base_urls_returns_first_candidate_and_handles_invalid_urls() -> (
    None
):
    assert derive_http_base_urls("dxtick://host:8011")[0] == "http://host:8011"
    assert derive_http_base_urls("dxctick://h1:8010|h2:8011") == ()
    assert derive_http_base_urls("not a url") == ()


def test_derive_http_base_urls_adds_8021_fallback() -> None:
    assert derive_http_base_urls("dxtick://tb.example.com:8011") == (
        "http://tb.example.com:8011",
        "http://tb.example.com:8021",
        "https://tb.example.com:8011",
        "https://tb.example.com:8021",
    )


def test_derive_http_base_urls_prefers_https_for_ssl_termination(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DXAPI_SSL_TERMINATION", "true")

    assert derive_http_base_urls("dxtick://tb.example.com:8011") == (
        "https://tb.example.com:8011",
        "https://tb.example.com:8021",
        "http://tb.example.com:8011",
        "http://tb.example.com:8021",
    )


def test_derive_http_base_urls_does_not_add_8021_for_custom_port() -> None:
    assert derive_http_base_urls("dxtick://tb.example.com:9011") == (
        "http://tb.example.com:9011",
        "https://tb.example.com:9011",
    )


def test_http_base_url_candidates_preserves_pathful_candidates() -> None:
    assert http_base_url_candidates(
        (
            "https://example.com",
            "https://example.com/tb",
            "https://example.com/tb/",
            "",
        )
    ) == (
        "https://example.com",
        "https://example.com/tb",
        "https://example.com/tb",
    )


def test_build_tb_url_accepts_root_or_tb_base() -> None:
    assert build_tb_url("http://host:8021", "/ping") == "http://host:8021/tb/ping"
    assert build_tb_url("http://host:8021/", "ping") == "http://host:8021/tb/ping"
    assert build_tb_url("http://host:8021/tb", "/ping") == "http://host:8021/tb/ping"
    assert (
        build_tb_url("https://proxy.example.com/timebase", "/api/info")
        == "https://proxy.example.com/timebase/tb/api/info"
    )
    assert (
        build_tb_url("https://proxy.example.com/timebase/tb", "tb/api/info")
        == "https://proxy.example.com/timebase/tb/api/info"
    )
    assert (
        build_tb_url("https://example.com/tb", "/ping") == "https://example.com/tb/ping"
    )


def test_derive_http_base_urls_prefers_https_for_ssl_scheme() -> None:
    assert derive_http_base_urls("dstick://tb.example.com:8011") == (
        "https://tb.example.com:8011",
        "https://tb.example.com:8021",
        "http://tb.example.com:8011",
        "http://tb.example.com:8021",
    )


def test_get_http_base_url_uses_8021_when_same_port_fails() -> None:
    instance = _http_instance(http_base_url=None)

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == "http://tb.example.com:8011/tb/ping":
            return httpx.Response(404)
        if str(request.url) == "http://tb.example.com:8021/tb/ping":
            return httpx.Response(200)
        raise AssertionError(f"unexpected URL: {request.url}")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        http_base_url = get_http_base_url(
            instance,
            client=client,
        )

    assert http_base_url == "http://tb.example.com:8021"
    assert instance.resolved_http_base_url == "http://tb.example.com:8021"


def test_get_http_base_url_treats_unauthorized_ping_as_reachable() -> None:
    instance = _http_instance(http_base_url="https://tb.example.com:8021")

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://tb.example.com:8021/tb/ping"
        return httpx.Response(403)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        http_base_url = get_http_base_url(
            instance,
            client=client,
        )

    assert http_base_url == "https://tb.example.com:8021"


def test_timebase_http_request_builds_tb_url() -> None:
    instance = _http_instance(http_base_url="https://example.com/tb")

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == "https://example.com/tb/ping":
            return httpx.Response(200)
        assert request.method == "POST"
        assert str(request.url) == "https://example.com/tb/api/info"
        return httpx.Response(200, json={"ok": True})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        response = timebase_http_request(
            instance,
            "/api/info",
            method="POST",
            client=client,
            json={"request": True},
        )

    assert response.json() == {"ok": True}


def test_timebase_http_request_reuses_cached_http_url() -> None:
    instance = _http_instance(http_base_url="https://example.com/tb")
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if str(request.url) == "https://example.com/tb/ping":
            return httpx.Response(200)
        return httpx.Response(200)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        timebase_http_request(instance, "/api/info", client=client)
        timebase_http_request(instance, "/api/connections", client=client)

    assert calls == [
        "https://example.com/tb/ping",
        "https://example.com/tb/api/info",
        "https://example.com/tb/api/connections",
    ]


def test_timebase_http_request_checks_ping_on_endpoint_404() -> None:
    instance = _http_instance(
        tb_url="dxtick://tb.example.com:8011",
        http_base_url=None,
    )
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        calls.append(url)
        if url == "http://tb.example.com:8011/tb/ping":
            return httpx.Response(200)
        if url == "http://tb.example.com:8011/tb/api/info":
            return httpx.Response(404)
        raise AssertionError(f"unexpected URL: {url}")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        instance.resolved_http_base_url = "http://tb.example.com:8011"
        response = timebase_http_request(
            instance,
            "/api/info",
            client=client,
        )

    assert response.status_code == 404
    assert instance.resolved_http_base_url == "http://tb.example.com:8011"
    assert calls == [
        "http://tb.example.com:8011/tb/api/info",
        "http://tb.example.com:8011/tb/ping",
    ]


def test_timebase_http_request_retries_endpoint_404_when_ping_finds_new_base() -> None:
    instance = _http_instance(
        tb_url="dxtick://tb.example.com:8011",
        http_base_url=None,
    )
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        calls.append(url)
        if url == "http://tb.example.com:8011/tb/api/info":
            return httpx.Response(404)
        if url == "http://tb.example.com:8011/tb/ping":
            return httpx.Response(404)
        if url == "http://tb.example.com:8021/tb/ping":
            return httpx.Response(200)
        if url == "http://tb.example.com:8021/tb/api/info":
            return httpx.Response(200, json={"ok": True})
        raise AssertionError(f"unexpected URL: {url}")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        instance.resolved_http_base_url = "http://tb.example.com:8011"
        response = timebase_http_request(
            instance,
            "/api/info",
            client=client,
        )

    assert response.json() == {"ok": True}
    assert instance.resolved_http_base_url == "http://tb.example.com:8021"
    assert calls == [
        "http://tb.example.com:8011/tb/api/info",
        "http://tb.example.com:8011/tb/ping",
        "http://tb.example.com:8021/tb/ping",
        "http://tb.example.com:8021/tb/api/info",
    ]


def test_timebase_http_request_sends_basic_auth_header() -> None:
    instance = TimeBaseInstanceRuntime(
        key="default",
        config=TimeBaseInstanceConfig(
            tb_url="dxtick://tb.example.com:8011",
            http_base_url="https://tb.example.com:8021",
            auth_mode="basic",
            tb_username="alice",
            tb_password=SecretStr("secret"),
        ),
    )
    expected = "Basic " + b64encode(b"alice:secret").decode("ascii")

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == "https://tb.example.com:8021/tb/ping":
            assert "authorization" not in request.headers
            return httpx.Response(200)
        assert request.headers["authorization"] == expected
        return httpx.Response(200, json={"ok": True})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        response = timebase_http_request(instance, "/api/info", client=client)

    assert response.json() == {"ok": True}


def test_timebase_http_request_sends_oauth2_bearer_from_shared_provider() -> None:
    instance = TimeBaseInstanceRuntime(
        key="default",
        config=TimeBaseInstanceConfig(
            tb_url="dxtick://tb.example.com:8011",
            http_base_url="https://tb.example.com:8021",
            auth_mode="oauth2_client_credentials",
            tb_username="service-user",
            tb_oauth2_token_url="https://idp.example/token",
            tb_oauth2_client_id="client-id",
            tb_oauth2_client_secret=SecretStr("client-secret"),
        ),
    )
    provider = _StaticTokenProvider("service-token")
    instance.oauth2_provider = provider

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == "https://tb.example.com:8021/tb/ping":
            assert "authorization" not in request.headers
            return httpx.Response(200)
        assert request.headers["authorization"] == "Bearer service-token"
        return httpx.Response(200, json={"ok": True})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        timebase_http_request(instance, "/api/info", client=client)
        timebase_http_request(instance, "/api/connections", client=client)

    assert provider.calls == 2


def test_timebase_http_request_does_not_auth_ping_or_explicit_no_auth() -> None:
    instance = TimeBaseInstanceRuntime(
        key="default",
        config=TimeBaseInstanceConfig(
            tb_url="dxtick://tb.example.com:8011",
            http_base_url="https://tb.example.com:8021",
            auth_mode="basic",
            tb_username="alice",
            tb_password=SecretStr("secret"),
        ),
    )
    calls: list[tuple[str, str | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((str(request.url), request.headers.get("authorization")))
        return httpx.Response(200, json={})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        timebase_http_request(instance, "/oauthinfo", client=client, auth=False)

    assert calls == [
        ("https://tb.example.com:8021/tb/ping", None),
        ("https://tb.example.com:8021/tb/oauthinfo", None),
    ]


def test_timebase_http_request_sends_forwarded_identity_bearer() -> None:
    instance = TimeBaseInstanceRuntime(
        key="default",
        config=TimeBaseInstanceConfig(
            tb_url="dxtick://tb.example.com:8011",
            http_base_url="https://tb.example.com:8021",
            auth_mode="forward_identity",
        ),
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == "https://tb.example.com:8021/tb/ping":
            assert "authorization" not in request.headers
            return httpx.Response(200)
        assert request.headers["authorization"] == "Bearer caller-token"
        return httpx.Response(200, json={"ok": True})

    access = AccessToken(
        token="caller-token",
        client_id="cid",
        scopes=[],
        subject="user-1",
        claims={"preferred_username": "alice"},
    )
    reset = auth_context_var.set(AuthenticatedUser(access))
    try:
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            response = timebase_http_request(instance, "/api/info", client=client)
    finally:
        auth_context_var.reset(reset)

    assert response.json() == {"ok": True}
