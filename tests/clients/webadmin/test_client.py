from __future__ import annotations

import time
from contextlib import contextmanager

import httpx2
import pytest

from timebase_mcp.clients import webadmin
from timebase_mcp.config.settings import MCPSettings
from timebase_mcp.errors import (
    TimeBaseOperationError,
    TimeBaseOperationTimeoutError,
)
from timebase_mcp.runtime.instance import TimeBaseInstanceRuntime
from timebase_mcp.runtime.operations import run_http_with_runtime
from timebase_mcp.runtime.state import build_runtime


def _response(status_code: int, *, content: bytes = b"{}") -> httpx2.Response:
    return httpx2.Response(
        status_code,
        request=httpx2.Request("GET", "http://webadmin.example.com/test"),
        content=content,
    )


@pytest.mark.parametrize(
    ("provider_type", "expected"),
    [
        ("EXTERNAL_OAUTH", "EXTERNAL_OAUTH"),
        ("SSO", "SSO"),
        ("SSO_BFF", "SSO_BFF"),
        ("UNRECOGNIZED", "unknown"),
        (None, "unknown"),
    ],
)
def test_webadmin_password_auth_fails_closed_for_unsupported_provider(
    webadmin_instance: TimeBaseInstanceRuntime,
    monkeypatch: pytest.MonkeyPatch,
    provider_type: object,
    expected: str,
) -> None:
    monkeypatch.setattr(
        webadmin,
        "get_webadmin_json",
        lambda instance, endpoint, *, authenticated: {"provider_type": provider_type},
    )

    with pytest.raises(
        TimeBaseOperationError,
        match=rf"supports BUILT_IN_OAUTH only; the server reports {expected}",
    ):
        webadmin.get_webadmin_payload(webadmin_instance, "/api/v0/topics")


@pytest.mark.parametrize(
    ("status_code", "message"),
    [
        (401, "rejected authentication"),
        (403, "denied permission"),
        (404, "is not available"),
    ],
)
def test_webadmin_payload_maps_expected_http_errors(
    webadmin_instance: TimeBaseInstanceRuntime,
    monkeypatch: pytest.MonkeyPatch,
    status_code: int,
    message: str,
) -> None:
    monkeypatch.setattr(
        webadmin, "http_request", lambda *args, **kwargs: _response(status_code)
    )

    with pytest.raises(TimeBaseOperationError, match=message):
        webadmin.get_webadmin_payload(webadmin_instance, "/test", authenticated=False)


def test_webadmin_payload_rejects_malformed_json(
    webadmin_instance: TimeBaseInstanceRuntime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        webadmin,
        "http_request",
        lambda *args, **kwargs: _response(200, content=b"not-json"),
    )

    with pytest.raises(TimeBaseOperationError, match="Expected JSON response"):
        webadmin.get_webadmin_payload(webadmin_instance, "/test", authenticated=False)


def test_webadmin_auth_error_redacts_configured_credentials(
    webadmin_instance: TimeBaseInstanceRuntime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    encoded_client = "Y2xpZW50LWlkOmNsaWVudC1zZWNyZXQ="

    class FailingProvider:
        def __init__(self, config: object) -> None:
            del config

        def get_access_token(self) -> str:
            raise PermissionError(
                f"user-password client-secret {encoded_client} "
                "access_token=unexpected-secret " + "x" * 10000
            )

    monkeypatch.setattr(
        webadmin,
        "get_webadmin_json",
        lambda instance, endpoint, *, authenticated: {
            "provider_type": "BUILT_IN_OAUTH",
            "oauth_server": "http://webadmin.example.com",
            "token_endpoint": "/oauth/token",
        },
    )
    monkeypatch.setattr(webadmin, "OAuth2PasswordProvider", FailingProvider)

    with pytest.raises(TimeBaseOperationError) as error:
        webadmin.get_webadmin_payload(webadmin_instance, "/api/v0/topics")

    assert "user-password" not in str(error.value)
    assert "client-secret" not in str(error.value)
    assert encoded_client not in str(error.value)
    assert "unexpected-secret" not in str(error.value)
    assert len(str(error.value)) < 500
    assert "token request was rejected" in str(error.value)


@pytest.mark.anyio
async def test_webadmin_http_operation_times_out() -> None:
    runtime = build_runtime(MCPSettings(operation_timeout_seconds=1))

    def slow_operation(instance: object) -> None:
        del instance
        time.sleep(1.1)

    try:
        with pytest.raises(
            TimeBaseOperationTimeoutError, match="HTTP operation timed out"
        ):
            await run_http_with_runtime(runtime, slow_operation)
    finally:
        await runtime.aclose()


@pytest.mark.parametrize("status", [200, 201, 202, 204, 206])
def test_inspection_requires_http_200(
    webadmin_instance: TimeBaseInstanceRuntime, monkeypatch, status
):
    monkeypatch.setattr(
        webadmin,
        "http_request",
        lambda *args, **kwargs: _response(status, content=b'["private-value"]'),
    )
    if status == 200:
        assert webadmin.get_webadmin_payload(
            webadmin_instance, "/api/v0/topics", authenticated=False
        ) == ["private-value"]
    else:
        with pytest.raises(TimeBaseOperationError, match=f"HTTP {status}") as exc:
            webadmin.get_webadmin_payload(
                webadmin_instance, "/api/v0/topics", authenticated=False
            )
        assert "private-value" not in str(exc.value)


@pytest.mark.parametrize("profile", ["public", "password", "api_key", "session"])
def test_webadmin_tls_ignores_native_trust_override(
    webadmin_instance: TimeBaseInstanceRuntime, monkeypatch, profile
):
    from dataclasses import replace

    from pydantic import SecretStr

    from timebase_mcp.auth.webadmin_session import WebAdminSession
    from timebase_mcp.config.webadmin import WebAdminAuthConfig, WebAdminConfig

    monkeypatch.setenv("DXAPI_SSL_TRUST_ALL", "true")
    instance = webadmin_instance
    auth = instance.config.webadmin.auth
    if profile in {"api_key", "session"}:
        auth = WebAdminAuthConfig(
            api_key="fixture-key",
            api_secret=SecretStr("fixture-secret") if profile == "api_key" else None,
            private_key_file="fixture.pem" if profile == "session" else None,
        )
    instance.config = replace(
        instance.config,
        webadmin=WebAdminConfig(url="https://webadmin.example", auth=auth),
    )
    calls = []

    class Provider:
        def get_access_token(self):
            return "fixture-token"

    instance.webadmin_provider = Provider()
    if profile == "session":

        def acquire(key, private_path, post):
            post("/attempt", {})
            post("/confirm", {})
            return WebAdminSession("session", b"secret", 60, time.monotonic() + 60)

        monkeypatch.setattr(WebAdminSession, "acquire", acquire)

    @contextmanager
    def stream(method, url, **kwargs):
        calls.append((method, kwargs["verify"]))
        yield httpx2.Response(200, json={}, request=httpx2.Request(method, url))

    monkeypatch.setattr(httpx2, "stream", stream)
    assert (
        webadmin.get_webadmin_payload(
            instance, "/api/v0/topics", authenticated=profile != "public"
        )
        == {}
    )
    expected = [("POST", True), ("POST", True)] if profile == "session" else []
    assert calls == expected + [("GET", True)]
