import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx2
import pytest
from pydantic import SecretStr, ValidationError

from timebase_mcp.auth import webadmin_oauth
from timebase_mcp.auth.oauth2 import UrlLibTokenEndpointClient
from timebase_mcp.auth.webadmin_oauth import WebAdminInteractiveProvider
from timebase_mcp.clients import webadmin
from timebase_mcp.config.servers import ServerConfig
from timebase_mcp.config.settings import MCPSettings
from timebase_mcp.config.webadmin import WebAdminAuthConfig, WebAdminConfig
from timebase_mcp.errors import TimeBaseOperationError
from timebase_mcp.runtime.instance import TimeBaseInstanceRuntime
from timebase_mcp.runtime.state import build_runtime

ISSUER = "https://idp.example/tenant/v2.0"


@pytest.fixture
def protected_requests(monkeypatch):
    headers = []

    def request(method, url, **kwargs):
        headers.append(kwargs["headers"])
        return httpx2.Response(200, json=[], request=httpx2.Request(method, url))

    monkeypatch.setattr(webadmin, "http_request", request)
    return headers


def settings(**changes):
    values: dict[str, object] = {
        "mode": "interactive",
        "client_id": "native",
        "issuer_url": ISSUER,
        "scope": "openid offline_access api://resource/access",
        "redirect_uri": "http://localhost:8765/",
    }
    values.update(changes)
    return MCPSettings(
        webadmin=WebAdminConfig(
            url="http://localhost:8099", auth=WebAdminAuthConfig.model_validate(values)
        )
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"client_secret": SecretStr("secret")},
        {"username": "user", "password": SecretStr("password")},
        {"issuer_url": "http://idp.example"},
        {"redirect_uri": "http://0.0.0.0:8765/"},
        {"redirect_uri": "http://localhost:8765/?x=1"},
        {"scope": None},
        {"api_key": "key", "api_secret": SecretStr("secret")},
    ],
)
def test_invalid_interactive_configuration(changes):
    with pytest.raises((ValidationError, ValueError)):
        settings(**changes)


def test_flat_indexed_and_json_settings(monkeypatch):
    for suffix, value in {
        "URL": "dxtick://localhost:8011",
        "WEBADMIN_URL": "http://localhost:8099",
        "WEBADMIN_AUTH_MODE": "interactive",
        "WEBADMIN_CLIENT_ID": "native",
        "WEBADMIN_ISSUER_URL": ISSUER,
        "WEBADMIN_SCOPE": "api://resource/access",
        "WEBADMIN_REDIRECT_URI": "http://localhost:8765/",
    }.items():
        monkeypatch.setenv("TIMEBASE_SERVERS_0_" + suffix, value)
    indexed = MCPSettings().resolve_servers()[0]
    assert indexed.webadmin.auth.mode == "interactive"
    assert indexed.webadmin.auth.client_id == "native"
    assert ServerConfig.model_validate_json(indexed.model_dump_json()) == indexed
    with pytest.raises(ValidationError, match="TIMEBASE_SERVERS cannot be combined"):
        MCPSettings(
            webadmin=WebAdminConfig(
                url="http://localhost:8099",
                auth=WebAdminAuthConfig(mode="bearer_file", token_file="/tmp/token"),
            )
        )


@pytest.mark.parametrize("profile", ["SSO", "SSO_BFF", "EXTERNAL_OAUTH"])
def test_interactive_request_reuse_refresh_and_401(monkeypatch, profile):
    instance = build_runtime(settings()).get_instance()
    posts = []
    status = [200]

    def http(method, url, **kwargs):
        if url.endswith("/authInfo"):
            payload = {
                "provider_type": profile,
                "config_url": ISSUER + "/.well-known/openid-configuration"
                if profile == "SSO"
                else None,
            }
        elif url.endswith("/.well-known/openid-configuration"):
            assert kwargs["follow_redirects"] is False
            payload = {
                "issuer": ISSUER,
                "authorization_endpoint": "https://idp.example/auth",
                "token_endpoint": "https://idp.example/token",
            }
        else:
            assert kwargs["headers"] == {"Authorization": "Bearer access"}
            return httpx2.Response(
                status[0], json=[], request=httpx2.Request(method, url)
            )
        return httpx2.Response(200, json=payload, request=httpx2.Request(method, url))

    def post_form(self, url, fields):
        assert url == "https://idp.example/token"
        posts.append(fields["grant_type"])
        return {
            "access_token": "access",
            "refresh_token": "refresh",
            "expires_in": 3600,
        }

    monkeypatch.setattr(UrlLibTokenEndpointClient, "post_form", post_form)

    def login(self):
        self._exchange_code(
            self._get_endpoints(), "code", "verifier", "http://localhost:8765/"
        )

    monkeypatch.setattr(webadmin, "http_request", http)
    monkeypatch.setattr(webadmin_oauth, "http_request", http)
    monkeypatch.setattr(WebAdminInteractiveProvider, "_login", login)
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert (
            list(
                pool.map(
                    lambda _: webadmin.get_webadmin_payload(
                        instance, "/api/v0/streams"
                    ),
                    range(8),
                )
            )
            == [[]] * 8
        )
    assert posts == ["authorization_code"]
    provider = instance.webadmin_provider
    assert isinstance(provider, WebAdminInteractiveProvider)
    provider._expires_at_monotonic = 0
    webadmin.get_webadmin_payload(instance, "/api/v0/streams")
    assert posts == ["authorization_code", "refresh_token"]
    status[0] = 403
    with pytest.raises(TimeBaseOperationError):
        webadmin.get_webadmin_payload(instance, "/api/v0/streams")
    assert instance.webadmin_provider is provider
    status[0] = 401
    with pytest.raises(TimeBaseOperationError):
        webadmin.get_webadmin_payload(instance, "/api/v0/streams")
    assert instance.webadmin_provider is None


@pytest.mark.parametrize(
    "profile", ["BUILT_IN_OAUTH", "EXTERNAL_OAUTH", "SSO", "SSO_BFF"]
)
def test_bearer_file_rotation_and_profiles(
    tmp_path: Path, monkeypatch, profile, protected_requests
):
    path = tmp_path / "token"
    path.write_text("first")
    instance = build_runtime(
        MCPSettings(
            webadmin=WebAdminConfig(
                url="http://localhost:8099",
                auth=WebAdminAuthConfig(mode="bearer_file", token_file=str(path)),
            ),
        )
    ).get_instance()
    monkeypatch.setattr(
        webadmin, "get_webadmin_json", lambda *a, **kw: {"provider_type": profile}
    )
    assert webadmin.get_webadmin_payload(instance, "/api/v0/topics") == []
    assert protected_requests[-1] == {"Authorization": "Bearer first"}
    path.write_text("second")
    assert webadmin.get_webadmin_payload(instance, "/api/v0/topics") == []
    assert protected_requests[-1] == {"Authorization": "Bearer second"}
    assert len(protected_requests) == 2
    path.write_text("bad\nheader")
    with pytest.raises(TimeBaseOperationError):
        webadmin.get_webadmin_payload(instance, "/api/v0/topics")
    assert len(protected_requests) == 2


def test_remote_interactive_rejected_before_discovery():
    instance = build_runtime(settings()).get_instance()
    instance.runtime_is_http_transport = True
    with pytest.raises(TimeBaseOperationError, match="stdio"):
        webadmin.get_webadmin_payload(instance, "/api/v0/topics")


@pytest.mark.parametrize(
    "metadata",
    [
        {"issuer": "https://wrong.example"},
        {
            "issuer": ISSUER,
            "authorization_endpoint": "https://evil.example/auth",
            "token_endpoint": "https://idp.example/token",
        },
    ],
)
def test_oidc_trust_failure(monkeypatch, metadata):
    monkeypatch.setattr(
        webadmin_oauth,
        "http_request",
        lambda *a, **kw: httpx2.Response(200, json=metadata),
    )
    provider = WebAdminInteractiveProvider(issuer_override=ISSUER)
    with pytest.raises(ValueError):
        provider._get_endpoints()


def test_service_credentials_configuration_and_routing(monkeypatch, protected_requests):
    instance = build_runtime(
        MCPSettings(
            webadmin=WebAdminConfig(
                url="http://localhost:8099",
                auth=WebAdminAuthConfig(
                    mode="client_credentials",
                    token_url="https://idp.example/token",
                    client_id="service",
                    client_secret=SecretStr("secret"),
                    scope="api://resource/.default",
                ),
            ),
        )
    ).get_instance()
    monkeypatch.setattr(
        webadmin,
        "get_webadmin_json",
        lambda *a, **kw: {"provider_type": "EXTERNAL_OAUTH"},
    )
    captured = []

    def acquire(self):
        captured.append(self._config)
        return "service-token"

    monkeypatch.setattr(
        webadmin.OAuth2ClientCredentialsProvider, "get_access_token", acquire
    )
    assert webadmin.get_webadmin_payload(instance, "/api/v0/topics") == []
    assert protected_requests[-1] == {"Authorization": "Bearer service-token"}
    assert captured[0].scope == "api://resource/.default"


@pytest.mark.parametrize("result", ["valid", "wrong_state", "denied"])
def test_browser_pkce_and_callback_validation(monkeypatch, result):
    import base64
    import hashlib
    from urllib.parse import parse_qs, urlsplit

    from timebase_mcp.auth import interactive
    from timebase_mcp.auth.discovery import InteractiveEndpoints

    opened = []
    exchanged = []

    class Listener:
        def __init__(self, *args):
            pass

    monkeypatch.setattr(interactive, "_CallbackHTTPServer", Listener)
    provider = WebAdminInteractiveProvider(
        redirect_uri="http://localhost:8765/",
        open_browser=lambda url: opened.append(url) or True,
    )
    provider._endpoints = InteractiveEndpoints(
        "https://idp.example/auth",
        "https://idp.example/token",
        "native",
        "openid api://resource/access",
    )

    def callback(server):
        params = parse_qs(urlsplit(opened[0]).query)
        if result == "denied":
            return {"error": ["access_denied"], "state": params["state"]}
        return {
            "code": ["code"],
            "state": params["state"] if result == "valid" else ["wrong"],
        }

    def exchange(endpoints, code, verifier, redirect):
        params = parse_qs(urlsplit(opened[0]).query)
        challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
            .decode("ascii")
            .rstrip("=")
        )
        assert params["code_challenge"] == [challenge]
        assert params["code_challenge_method"] == ["S256"]
        assert params["client_id"] == ["native"]
        assert redirect == "http://localhost:8765/"
        exchanged.append(code)

    monkeypatch.setattr(provider, "_wait_for_callback", callback)
    monkeypatch.setattr(provider, "_exchange_code", exchange)
    if result == "valid":
        provider._login()
        assert exchanged == ["code"]
    else:
        with pytest.raises(PermissionError):
            provider._login()
        assert not exchanged


def test_bearer_instances_do_not_share_identity(
    tmp_path, monkeypatch, protected_requests
):
    entries = []
    for name in ("reader", "writer"):
        path = tmp_path / name
        path.write_text(name + "-token")
        entries.append(
            {
                "name": name,
                "url": "dxtick://localhost:8011",
                "webadmin_url": "http://localhost:8099",
                "webadmin_auth_mode": "bearer_file",
                "webadmin_token_file": str(path),
            }
        )
    runtime = build_runtime(MCPSettings.model_validate({"servers": entries}))
    monkeypatch.setattr(
        webadmin, "get_webadmin_json", lambda *a, **kw: {"provider_type": "SSO"}
    )
    for name in ("reader", "writer"):
        assert (
            webadmin.get_webadmin_payload(runtime.get_instance(name), "/api/v0/topics")
            == []
        )
        assert protected_requests[-1] == {"Authorization": "Bearer " + name + "-token"}


def test_unknown_provider_never_reads_token_file(monkeypatch):
    instance = build_runtime(
        MCPSettings(
            webadmin=WebAdminConfig(
                url="http://localhost:8099",
                auth=WebAdminAuthConfig(
                    mode="bearer_file", token_file="/does/not/exist"
                ),
            ),
        )
    ).get_instance()
    monkeypatch.setattr(
        webadmin, "get_webadmin_json", lambda *a, **kw: {"provider_type": "UNKNOWN"}
    )
    with pytest.raises(TimeBaseOperationError, match="Unknown WebAdmin"):
        webadmin.get_webadmin_payload(instance, "/api/v0/topics")


@pytest.mark.parametrize(
    "profile,config_url",
    [
        ("SSO", None),
        ("SSO_BFF", "https://evil.example/.well-known/openid-configuration"),
        ("EXTERNAL_OAUTH", "https://evil.example/.well-known/openid-configuration"),
        ("EXTERNAL_OAUTH", ""),
    ],
)
def test_discovery_mismatch_remains_rejected(monkeypatch, profile, config_url):
    instance = build_runtime(settings()).get_instance()
    monkeypatch.setattr(
        webadmin,
        "get_webadmin_json",
        lambda *a, **kw: {"provider_type": profile, "config_url": config_url},
    )
    with pytest.raises(TimeBaseOperationError, match="trusted issuer"):
        webadmin.get_webadmin_payload(instance, "/api/v0/topics")


def test_late_401_preserves_replacement_provider(monkeypatch):
    from threading import Event

    instance = build_runtime(settings()).get_instance()
    started, release = Event(), Event()
    providers = []

    class Provider:
        def __init__(self, **kwargs):
            providers.append(self)

        def get_access_token(self):
            return f"token-{providers.index(self)}"

    monkeypatch.setattr(webadmin, "WebAdminInteractiveProvider", Provider)
    monkeypatch.setattr(
        webadmin,
        "get_webadmin_json",
        lambda *a, **kw: {
            "provider_type": "SSO",
            "config_url": ISSUER + "/.well-known/openid-configuration",
        },
    )

    def request(method, url, **kwargs):
        if url.endswith("/late"):
            assert kwargs["headers"]["Authorization"] == "Bearer token-0"
            started.set()
            assert release.wait(5)
        status = 200 if url.endswith("/ok") else 401
        return httpx2.Response(status, json={}, request=httpx2.Request(method, url))

    monkeypatch.setattr(webadmin, "http_request", request)

    def rejected(path):
        with pytest.raises(TimeBaseOperationError, match="rejected authentication"):
            webadmin.get_webadmin_payload(instance, path)

    with ThreadPoolExecutor(max_workers=1) as executor:
        late = executor.submit(rejected, "/late")
        try:
            assert started.wait(5)
            rejected("/first")
            assert instance.webadmin_provider is None
            assert webadmin.get_webadmin_payload(instance, "/ok") == {}
            assert len(providers) == 2
        finally:
            release.set()
        late.result(timeout=5)
    assert webadmin.get_webadmin_payload(instance, "/ok") == {}
    assert len(providers) == 2
    assert instance.webadmin_provider is providers[1]


@pytest.mark.parametrize("refreshed_token", ["new-token", "old-token"])
def test_late_401_invalidates_only_the_rejected_token(monkeypatch, refreshed_token):
    from threading import Event

    instance = build_runtime(settings()).get_instance()
    provider = WebAdminInteractiveProvider(issuer_override=ISSUER)
    provider._access_token = "old-token"
    provider._refresh_token = "fixture-refresh"
    instance.webadmin_provider = provider
    started, release = Event(), Event()
    refreshes = []

    def refresh():
        refreshes.append(True)
        provider._access_token = refreshed_token
        provider._expires_at_monotonic = None

    def request(method, url, **kwargs):
        if url.endswith("/late"):
            assert kwargs["headers"]["Authorization"] == "Bearer old-token"
            started.set()
            assert release.wait(5)
            status = 401
        else:
            assert kwargs["headers"]["Authorization"] == f"Bearer {refreshed_token}"
            status = 200
        return httpx2.Response(status, json={}, request=httpx2.Request(method, url))

    def rejected():
        with pytest.raises(TimeBaseOperationError, match="rejected authentication"):
            webadmin.get_webadmin_payload(instance, "/late")

    monkeypatch.setattr(provider, "_refresh", refresh)
    monkeypatch.setattr(webadmin, "http_request", request)
    with ThreadPoolExecutor(max_workers=1) as executor:
        late = executor.submit(rejected)
        try:
            assert started.wait(5)
            provider._expires_at_monotonic = 0
            assert webadmin.get_webadmin_payload(instance, "/ok") == {}
        finally:
            release.set()
        late.result(timeout=5)
    assert refreshes == [True]
    if refreshed_token == "new-token":
        assert instance.webadmin_provider is provider
        assert webadmin.get_webadmin_payload(instance, "/ok") == {}
        assert refreshes == [True]
    else:
        assert instance.webadmin_provider is None


@pytest.mark.parametrize(
    "client_fields, expected_basic",
    [
        ({}, "Basic d2ViOnNlY3JldA=="),
        (
            {"client_id": "client-id", "client_secret": "client-secret"},
            "Basic Y2xpZW50LWlkOmNsaWVudC1zZWNyZXQ=",
        ),
    ],
)
def test_password_defaults_and_overrides(
    monkeypatch, protected_requests, client_fields, expected_basic
):
    instance = build_runtime(
        MCPSettings.model_validate(
            {
                "webadmin": {
                    "url": "http://localhost:8099",
                    "auth": {
                        "username": "admin",
                        "password": "password",
                        **client_fields,
                    },
                }
            }
        )
    ).get_instance()
    monkeypatch.setattr(
        webadmin,
        "get_webadmin_json",
        lambda *a, **kw: {
            "provider_type": "BUILT_IN_OAUTH",
            "token_endpoint": "/oauth/token",
        },
    )

    def post_form(self, url, fields, *, headers):
        assert url == "http://localhost:8099/oauth/token"
        assert fields == {
            "grant_type": "password",
            "scope": "trust",
            "username": "admin",
            "password": "password",
        }
        assert headers == {"Authorization": expected_basic}
        return {"access_token": "access"}

    monkeypatch.setattr(UrlLibTokenEndpointClient, "post_form", post_form)
    assert webadmin.get_webadmin_payload(instance, "/api/v0/topics") == []
    assert protected_requests == [{"Authorization": "Bearer access"}]


def test_webadmin_rejects_cross_origin_password_destination(
    webadmin_instance: TimeBaseInstanceRuntime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        webadmin,
        "get_webadmin_json",
        lambda *args, **kwargs: {
            "provider_type": "BUILT_IN_OAUTH",
            "oauth_server": "https://untrusted.example",
            "token_endpoint": "/oauth/token",
        },
    )
    monkeypatch.setattr(
        webadmin,
        "OAuth2PasswordProvider",
        lambda *args: pytest.fail("credentials sent to untrusted origin"),
    )
    with pytest.raises(TimeBaseOperationError, match="same origin"):
        webadmin.get_webadmin_payload(webadmin_instance, "/api/v0/topics")


def test_concurrent_webadmin_calls_share_one_token_acquisition(
    webadmin_instance: TimeBaseInstanceRuntime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    acquisitions = []

    class Provider:
        def __init__(self, config):
            self.token = None

        def get_access_token(self):
            if self.token is None:
                time.sleep(0.01)
                acquisitions.append(1)
                self.token = "fixture-token"
            return self.token

    monkeypatch.setattr(webadmin, "OAuth2PasswordProvider", Provider)
    monkeypatch.setattr(
        webadmin,
        "get_webadmin_json",
        lambda *args, **kwargs: {
            "provider_type": "BUILT_IN_OAUTH",
            "token_endpoint": "/oauth/token",
        },
    )

    def request(method, url, **kwargs):
        assert kwargs["headers"] == {"Authorization": "Bearer fixture-token"}
        return httpx2.Response(200, json=[], request=httpx2.Request(method, url))

    monkeypatch.setattr(webadmin, "http_request", request)
    instance = webadmin_instance
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(
            executor.map(
                lambda _: webadmin.get_webadmin_payload(instance, "/api/v0/topics"),
                range(4),
            )
        )
    assert acquisitions == [1]
    assert results == [[]] * 4
