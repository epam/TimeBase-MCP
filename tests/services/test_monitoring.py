from __future__ import annotations

import time

import httpx2
import jwt
import pytest
from pydantic import SecretStr

from timebase_mcp.config.settings import MCPSettings
from timebase_mcp.errors import TimeBaseOperationError
from timebase_mcp.runtime.state import TimeBaseRuntime, build_runtime
from timebase_mcp.services.monitoring import (
    get_timebase_activity_detail,
    get_timebase_status,
    list_timebase_activity,
)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _runtime(http_base_url: str = "http://tb.example.com:8021") -> TimeBaseRuntime:
    runtime = build_runtime(MCPSettings(tb_http_url=http_base_url))
    runtime.default_instance.resolved_http_base_url = http_base_url
    return runtime


def _basic_auth_runtime(
    http_base_url: str = "http://tb.example.com:8021",
) -> TimeBaseRuntime:
    runtime = build_runtime(
        MCPSettings(
            tb_http_url=http_base_url,
            tb_auth_mode="basic",
            tb_username="alice",
            tb_password=SecretStr("secret"),
        )
    )
    runtime.default_instance.resolved_http_base_url = http_base_url
    return runtime


class _StaticTokenProvider:
    def __init__(self, token: str) -> None:
        self.token = token
        self.calls = 0

    def get_access_token(self) -> str:
        self.calls += 1
        return self.token


def _response(url: str, *, method: str = "GET") -> httpx2.Response:
    request = httpx2.Request(method, url)
    parsed = httpx2.URL(url)
    path = parsed.path.split("/tb", 1)[1]
    if parsed.query:
        query = (
            parsed.query.decode()
            if isinstance(parsed.query, bytes)
            else str(parsed.query)
        )
        path += "?" + query
    if path == "/oauthinfo":
        return httpx2.Response(200, request=request, content=b"")
    if path == "/api/info":
        return httpx2.Response(
            200,
            request=request,
            json={
                "version": "5.7.13",
            },
        )
    if path == "/api/license":
        return httpx2.Response(
            200,
            request=request,
            json={
                "clientName": "ACME",
                "productName": "TimeBase",
                "version": "5.7",
                "expirationTime": "2026-12-31",
                "daysValid": 180,
                "validUntil": "2026-12-31",
                "offline": False,
                "lastValidateTime": "2026-06-29 10:00:00",
                "valid": True,
                "error": None,
            },
        )
    if path == "/api/server/security":
        return httpx2.Response(
            200,
            request=request,
            json={
                "enabled": True,
                "controllerType": "FILE",
            },
        )
    if path == "/api/server/system?gc=false":
        return httpx2.Response(
            200,
            request=request,
            json={
                "timestamp": 100,
                "cpuCount": 8,
                "maxMemoryMb": 4096,
                "usedMemoryMb": 1024,
                "currentMemoryMb": 2048,
                "availableMemoryMb": 3072,
                "systemProperties": {
                    "os.name": "Mac OS X",
                    "os.version": "14.0",
                    "os.arch": "x86_64",
                    "java.runtime.name": "OpenJDK Runtime Environment",
                    "java.version": "21",
                    "java.vendor": "Eclipse Adoptium",
                },
            },
        )
    if path == "/api/cursors":
        return httpx2.Response(
            200,
            request=request,
            json=[
                {
                    "id": 1,
                    "user": "u",
                    "application": "app",
                    "sourceStreamKeys": ["s1"],
                    "openTime": 10,
                    "totalNumMessages": 20,
                    "lastMessageTimestamp": 30,
                    "lastMessageSysTime": 40,
                }
            ],
        )
    if path == "/api/loaders":
        return httpx2.Response(
            200,
            request=request,
            json=[
                {
                    "id": 2,
                    "user": "u",
                    "application": "loader",
                    "targetStreamKey": "s2",
                    "openTime": 11,
                    "totalNumMessages": 21,
                    "lastMessageTimestamp": 31,
                    "lastMessageSysTime": 41,
                    "progress": 0.5,
                }
            ],
        )
    if path == "/api/connections":
        return httpx2.Response(
            200,
            request=request,
            json=[
                {
                    "clientId": "c1",
                    "applicationId": "app",
                    "creationTime": 12,
                    "remoteAddress": "127.0.0.1",
                    "numTransportChannels": 3,
                    "throughput": 1000,
                    "averageThroughput": 10.5,
                }
            ],
        )
    if path == "/api/locks":
        return httpx2.Response(
            200,
            request=request,
            json=[
                {
                    "id": 3,
                    "guid": "g1",
                    "type": "WRITE",
                    "clientId": "c1",
                    "streamKey": "s1",
                    "application": "app",
                    "user": "u",
                    "host": "h",
                }
            ],
        )
    if path == "/api/cursors/1":
        return httpx2.Response(
            200, request=request, json={"id": 1, "instrumentCount": 10}
        )
    if path == "/api/cursors/1/instruments?offset=5&limit=10&filter=AAPL":
        return httpx2.Response(
            200, request=request, json={"offset": 5, "limit": 10, "items": []}
        )
    if path == "/api/connections/c1":
        return httpx2.Response(
            200, request=request, json={"clientId": "c1", "channels": []}
        )
    return httpx2.Response(404, request=request, json={"message": "not found"})


@pytest.fixture(autouse=True)
def _mock_http(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_request(method: str, url: str, *, timeout: float, verify: bool, **kwargs):
        return _response(url, method=method)

    monkeypatch.setattr(
        "timebase_mcp.clients.http.transport.httpx2.request", fake_request
    )


@pytest.mark.anyio
async def test_get_timebase_status_includes_license_and_runtime() -> None:
    status = await get_timebase_status(_runtime())

    assert status.http_url == "http://tb.example.com:8021"
    assert status.version == "5.7.13"
    assert status.security is not None
    assert status.security.enabled is True
    assert status.security.controller_type == "FILE"
    assert status.license is not None
    assert status.license.valid_until == "2026-12-31"
    assert status.license.days_valid == 180
    assert status.runtime is not None
    assert status.runtime.cpu_count == 8
    assert status.runtime.os_name == "Mac OS X"
    assert status.runtime.java_version == "21"
    assert status.warnings == []


@pytest.mark.anyio
async def test_get_timebase_status_uses_configured_http_auth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = "Basic YWxpY2U6c2VjcmV0"

    def fake_request(method: str, url: str, *, timeout: float, verify: bool, **kwargs):
        if url != "http://tb.example.com:8021/tb/ping":
            assert kwargs["headers"]["Authorization"] == expected
        return _response(url, method=method)

    monkeypatch.setattr(
        "timebase_mcp.clients.http.transport.httpx2.request", fake_request
    )

    status = await get_timebase_status(_basic_auth_runtime())

    assert status.version == "5.7.13"
    assert status.warnings == []


@pytest.mark.anyio
async def test_get_timebase_status_auto_discovers_oauth_and_uses_bearer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = build_runtime(
        MCPSettings(
            tb_http_url="http://tb.example.com:8021",
            tb_auth_mode="auto",
            tb_username="service-user",
            tb_oauth2_token_url="https://idp.example/token",
            tb_oauth2_client_id="client-id",
            tb_oauth2_client_secret=SecretStr("client-secret"),
        )
    )
    runtime.default_instance.resolved_http_base_url = "http://tb.example.com:8021"
    token = jwt.encode(
        {"preferred_username": "service-user"},
        "test-secret-key-that-is-long-enough",
        algorithm="HS256",
    )
    provider = _StaticTokenProvider(token)
    runtime.default_instance.oauth2_provider = provider

    calls: list[str] = []

    def fake_request(method: str, url: str, *, timeout: float, verify: bool, **kwargs):
        calls.append(url)
        if url == "http://tb.example.com:8021/tb/oauthinfo":
            assert "headers" not in kwargs or "Authorization" not in kwargs["headers"]
            return httpx2.Response(
                200,
                request=httpx2.Request(method, url),
                json={"issuer": "https://idp.example"},
            )
        if url != "http://tb.example.com:8021/tb/ping":
            assert kwargs["headers"]["Authorization"] == "Bearer " + token
        return _response(url, method=method)

    monkeypatch.setattr(
        "timebase_mcp.clients.http.transport.httpx2.request", fake_request
    )

    status = await get_timebase_status(runtime)

    assert status.version == "5.7.13"
    assert runtime.default_instance.config.auth_mode == "oauth2_client_credentials"
    assert provider.calls == 4
    assert "http://tb.example.com:8021/tb/oauthinfo" in calls


@pytest.mark.anyio
async def test_get_timebase_status_warns_when_license_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_request(method: str, url: str, *, timeout: float, verify: bool, **kwargs):
        if url.endswith("/tb/api/license") or url.endswith("/tb/api/server/security"):
            return httpx2.Response(
                500, request=httpx2.Request(method, url), json={"message": "boom"}
            )
        return _response(url, method=method)

    monkeypatch.setattr(
        "timebase_mcp.clients.http.transport.httpx2.request", fake_request
    )

    status = await get_timebase_status(_runtime())

    assert status.version == "5.7.13"
    assert status.license is None
    assert status.security is None
    assert len(status.warnings) == 2


@pytest.mark.anyio
async def test_get_timebase_status_reports_missing_monitor_api_after_connection_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def fake_request(method: str, url: str, *, timeout: float, verify: bool, **kwargs):
        calls.append(url)
        request = httpx2.Request(method, url)
        if url == "http://tb.example.com:8021/tb/ping":
            return httpx2.Response(200, request=request)
        if url == "http://tb.example.com:8021/tb/oauthinfo":
            return httpx2.Response(200, request=request, content=b"")
        if url == "http://tb.example.com:8021/tb/api/info":
            return httpx2.Response(404, request=request, json={"message": "not found"})
        raise AssertionError(f"unexpected URL: {url}")

    monkeypatch.setattr(
        "timebase_mcp.clients.http.transport.httpx2.request", fake_request
    )

    with pytest.raises(TimeBaseOperationError) as exc_info:
        await get_timebase_status(_runtime())

    assert "TimeBase Monitor API endpoint /api/info is not available" in str(
        exc_info.value
    )
    assert calls == [
        "http://tb.example.com:8021/tb/oauthinfo",
        "http://tb.example.com:8021/tb/api/info",
        "http://tb.example.com:8021/tb/ping",
    ]


@pytest.mark.anyio
async def test_list_timebase_activity_all_kinds() -> None:
    activity = await list_timebase_activity(_runtime(), kind="all", limit=10)

    assert activity.counts.cursors == 1
    assert activity.cursors[0].source_stream_keys == ["s1"]
    assert activity.loaders[0].target_stream_key == "s2"
    assert activity.connections[0].client_id == "c1"
    assert activity.locks[0].guid == "g1"


@pytest.mark.anyio
async def test_list_timebase_activity_reports_warnings_when_monitor_api_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_request(method: str, url: str, *, timeout: float, verify: bool, **kwargs):
        request = httpx2.Request(method, url)
        if url == "http://tb.example.com:8021/tb/ping":
            return httpx2.Response(200, request=request)
        if url == "http://tb.example.com:8021/tb/oauthinfo":
            return httpx2.Response(200, request=request, content=b"")
        if url.startswith("http://tb.example.com:8021/tb/api/"):
            return httpx2.Response(404, request=request, json={"message": "not found"})
        raise AssertionError(f"unexpected URL: {url}")

    monkeypatch.setattr(
        "timebase_mcp.clients.http.transport.httpx2.request", fake_request
    )

    activity = await list_timebase_activity(_runtime(), kind="all", limit=10)

    assert activity.counts.cursors == 0
    assert activity.counts.loaders == 0
    assert activity.counts.connections == 0
    assert activity.counts.locks == 0
    assert activity.cursors == []
    assert activity.loaders == []
    assert activity.connections == []
    assert activity.locks == []
    assert activity.warnings == [
        "/api/cursors unavailable: TimeBase Monitor API endpoint /api/cursors is not available.",
        "/api/loaders unavailable: TimeBase Monitor API endpoint /api/loaders is not available.",
        "/api/connections unavailable: TimeBase Monitor API endpoint /api/connections is not available.",
        "/api/locks unavailable: TimeBase Monitor API endpoint /api/locks is not available.",
    ]


@pytest.mark.anyio
async def test_get_activity_detail_fetches_instruments() -> None:
    detail = await get_timebase_activity_detail(
        _runtime(),
        kind="cursor",
        id="1",
        include_instruments=True,
        instrument_offset=5,
        instrument_limit=10,
        instrument_filter="AAPL",
    )

    assert detail.detail == {"id": 1, "instrumentCount": 10}
    assert detail.instruments == {"offset": 5, "limit": 10, "items": []}


@pytest.mark.anyio
async def test_monitoring_uses_operation_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = build_runtime(
        MCPSettings(tb_http_url="http://tb.example.com:8021", max_concurrent_ops=1)
    )
    runtime.default_instance.resolved_http_base_url = "http://tb.example.com:8021"

    def fake_request(method: str, url: str, *, timeout: float, verify: bool, **kwargs):
        time.sleep(0.2)
        return _response(url, method=method)

    monkeypatch.setattr(
        "timebase_mcp.clients.http.transport.httpx2.request", fake_request
    )

    import asyncio

    first = asyncio.create_task(get_timebase_status(runtime))
    await asyncio.sleep(0.05)
    with pytest.raises(Exception, match="Maximum concurrent TimeBase operations"):
        await get_timebase_status(runtime)
    await first


@pytest.mark.parametrize(
    ("id", "expected_segment"),
    [
        ("../server/system?gc=true", "..%2Fserver%2Fsystem%3Fgc%3Dtrue"),
        ("1?offset=999", "1%3Foffset%3D999"),
    ],
)
@pytest.mark.anyio
async def test_get_activity_detail_escapes_the_id_path_segment(
    monkeypatch: pytest.MonkeyPatch,
    id: str,
    expected_segment: str,
) -> None:
    requested: list[str] = []

    def recording_request(method: str, url: str, **kwargs: object):
        requested.append(url)
        return _response(url, method=method)

    monkeypatch.setattr(
        "timebase_mcp.clients.http.transport.httpx2.request", recording_request
    )

    with pytest.raises(TimeBaseOperationError):
        await get_timebase_activity_detail(
            _runtime(),
            kind="cursor",
            id=id,
            include_instruments=False,
            instrument_offset=0,
            instrument_limit=50,
            instrument_filter=None,
        )

    assert any(url.endswith(f"/tb/api/cursors/{expected_segment}") for url in requested)
