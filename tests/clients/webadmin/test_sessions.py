from __future__ import annotations

import base64
import hashlib
import hmac
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx2
import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from pydantic import ValidationError

from timebase_mcp.auth.webadmin_session import WebAdminSession
from timebase_mcp.clients import webadmin
from timebase_mcp.config.servers import ServerConfig
from timebase_mcp.config.settings import MCPSettings
from timebase_mcp.config.webadmin import WebAdminAuthConfig, WebAdminConfig
from timebase_mcp.errors import TimeBaseOperationError
from timebase_mcp.runtime.state import build_runtime

# RFC 3526 group 14, also the library 0.1.6 default.
MODULUS = int(
    "ffffffffffffffffc90fdaa22168c234c4c6628b80dc1cd129024e088a67cc74020bbea63b139b22514a08798e3404ddef9519b3cd"
    "3a431b302b0a6df25f14374fe1356d6d51c245e485b576625e7ec6f44c42e9a637ed6b0bff5cb6f406b7edee386bfb5a899"
    "fa5ae9f24117c4b1fe649286651ece45b3dc2007cb8a163bf0598da48361c55d39a69163fa8fd24cf5f83655d23dca3ad961c62"
    "f356208552bb9ed529077096966d670c354e4abc9804f1746c08ca18217c32905e462e36ce3be39e772c180e86039b2783a2"
    "ec07a28fb5c55df06f4c52c9de2bcbf6955817183995497cea956ae515d2261898fa051015728e5a8aacaa68ffffffffffffffff",
    16,
)


def encode_integer(number: int) -> str:
    return base64.b64encode(
        number.to_bytes((number.bit_length() + 8) // 8, "big")
    ).decode()


def test_session_handshake_signing_reuse_and_concurrency(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    path = tmp_path / "key.pem"
    path.write_bytes(
        private.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    runtime = build_runtime(
        MCPSettings(
            webadmin=WebAdminConfig(
                url="https://example.test/context",
                auth=WebAdminAuthConfig(api_key="reader", private_key_file=str(path)),
            ),
        )
    )
    instance = runtime.get_instance()
    secret = b""
    nonces = []
    attempts = []
    active = 0

    def request(method, url, **kwargs):
        nonlocal secret, active
        assert kwargs["follow_redirects"] is False
        assert kwargs["max_response_bytes"] <= 128 * 1024
        if url.endswith("/attempt"):
            attempts.append(1)
            assert kwargs["json"] == {"api_key_id": "reader"}
            data = {
                "session_id": "fixture-session",
                "dh_base": encode_integer(2),
                "dh_modulus": encode_integer(MODULUS),
                "challenge": base64.b64encode(b"fixture-challenge").decode(),
                "ttl": 10000,
            }
        elif url.endswith("/confirm"):
            body = kwargs["json"]
            private.public_key().verify(
                base64.b64decode(body["signature"]),
                b"fixture-challenge",
                padding.PKCS1v15(),
                hashes.SHA256(),
            )
            shared = pow(
                int.from_bytes(base64.b64decode(body["dh_key"]), "big"), 7, MODULUS
            )
            secret = shared.to_bytes((shared.bit_length() + 8) // 8, "big")
            data = {
                "dh_key": encode_integer(pow(2, 7, MODULUS)),
                "keepalive_timeout": 100000,
            }
        else:
            assert active == 0
            active += 1
            time.sleep(0.005)
            headers = kwargs["headers"]
            nonce = int(headers["X-Deltix-Nonce"])
            nonces.append(nonce)
            payload = f"GET/api/v0/topicsa=1&a=2X-Deltix-Nonce={nonce}&X-Deltix-Session-Id=fixture-session"
            assert (
                headers["X-Deltix-Signature"]
                == base64.b64encode(
                    hmac.new(secret, payload.encode(), hashlib.sha384).digest()
                ).decode()
            )
            active -= 1
            data = []
        return httpx2.Response(200, json=data, request=httpx2.Request(method, url))

    monkeypatch.setattr(webadmin, "http_request", request)
    with ThreadPoolExecutor(max_workers=4) as pool:
        values = list(
            pool.map(
                lambda _: webadmin.get_webadmin_payload(
                    instance, "/api/v0/topics?a=2&a=1"
                ),
                range(8),
            )
        )
    assert values == [[]] * 8
    assert attempts == [1]
    assert nonces == list(range(1, 9))
    assert instance.webadmin_session is not None
    instance.webadmin_session.expires_at = 0
    assert webadmin.get_webadmin_payload(instance, "/api/v0/topics?a=2&a=1") == []
    assert attempts == [1, 1]
    assert nonces[-1] == 1


@pytest.mark.parametrize("status", [400, 401, 403])
def test_session_response_invalidation(
    status: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    instance = build_runtime(
        MCPSettings(
            webadmin=WebAdminConfig(
                url="https://example.test",
                auth=WebAdminAuthConfig(api_key="reader", private_key_file="/unused"),
            ),
        )
    ).get_instance()
    session = WebAdminSession(
        "private-id", b"private-secret", 100, time.monotonic() + 100
    )
    instance.webadmin_session = session
    monkeypatch.setattr(
        webadmin,
        "http_request",
        lambda *a, **k: httpx2.Response(
            status,
            text="private-secret",
            request=httpx2.Request("GET", "https://example.test"),
        ),
    )
    with pytest.raises(TimeBaseOperationError) as error:
        webadmin.get_webadmin_payload(instance, "/api/v0/topics")
    assert "private-secret" not in str(error.value)
    assert (instance.webadmin_session is None) == (status in {400, 401})
    assert "private-secret" not in repr(session)


@pytest.mark.parametrize(
    "fields",
    [
        {"webadmin_private_key_file": "/key"},
        {"webadmin_api_key": "reader", "webadmin_private_key_file": ""},
        {
            "webadmin_api_key": "reader",
            "webadmin_private_key_file": "/key",
            "webadmin_api_secret": "secret",
        },
        {
            "webadmin_api_key": "reader",
            "webadmin_private_key_file": "/key",
            "webadmin_session_login_root": "https://other.test",
        },
        {
            "webadmin_api_key": "reader",
            "webadmin_private_key_file": "/key",
            "webadmin_session_login_root": "/../outside",
        },
        {"webadmin_session_login_root": "/session/login"},
    ],
)
def test_session_config_rejects_ambiguous_credentials_and_paths(
    fields: dict[str, str],
) -> None:
    with pytest.raises(ValidationError):
        ServerConfig.model_validate({"url": "dxtick://localhost:8011", **fields})
    with pytest.raises(ValidationError):
        MCPSettings.model_validate({"tb_" + k: v for k, v in fields.items()})


def test_private_key_failure_does_not_contact_server(tmp_path: Path) -> None:
    path = tmp_path / "invalid.pem"
    path.write_text("private-invalid-content")
    called = []

    def post(route, body):
        called.append(route)
        return {}

    with pytest.raises(TimeBaseOperationError) as error:
        WebAdminSession.acquire("reader", str(path), post)
    assert called == []
    assert "private-invalid-content" not in str(error.value)


def test_session_environment_and_runtime_mapping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TIMEBASE_WEBADMIN_API_KEY", "reader")
    monkeypatch.setenv("TIMEBASE_WEBADMIN_PRIVATE_KEY_FILE", "/private/key.pem")
    monkeypatch.setenv("TIMEBASE_WEBADMIN_SESSION_LOGIN_ROOT", "/custom/login")
    instance = build_runtime(MCPSettings()).get_instance()
    assert instance.config.webadmin.auth.private_key_file == "/private/key.pem"
    assert instance.config.webadmin.auth.session_login_root == "/custom/login"
    monkeypatch.delenv("TIMEBASE_WEBADMIN_API_KEY")
    monkeypatch.delenv("TIMEBASE_WEBADMIN_PRIVATE_KEY_FILE")
    monkeypatch.delenv("TIMEBASE_WEBADMIN_SESSION_LOGIN_ROOT")
    monkeypatch.setenv("TIMEBASE_SERVERS_0_URL", "dxtick://localhost:8011")
    monkeypatch.setenv("TIMEBASE_SERVERS_0_WEBADMIN_API_KEY", "writer")
    monkeypatch.setenv("TIMEBASE_SERVERS_0_WEBADMIN_PRIVATE_KEY_FILE", "/other/key.pem")
    monkeypatch.setenv("TIMEBASE_SERVERS_0_WEBADMIN_SESSION_LOGIN_ROOT", "/other/login")
    instance = build_runtime(MCPSettings()).get_instance()
    assert instance.config.webadmin.auth.api_key == "writer"
    assert instance.config.webadmin.auth.private_key_file == "/other/key.pem"
    assert instance.config.webadmin.auth.session_login_root == "/other/login"


@pytest.mark.parametrize(
    "fields",
    [
        {"session_id": "bad\r\nid"},
        {"session_id": "valid", "dh_modulus": "invalid!"},
        {
            "session_id": "valid",
            "dh_modulus": encode_integer(17),
            "dh_base": encode_integer(2),
        },
        {
            "session_id": "valid",
            "dh_modulus": encode_integer(MODULUS),
            "dh_base": encode_integer(1),
        },
    ],
)
def test_bad_handshake_fields_never_reach_confirmation(
    fields: dict[str, str], tmp_path: Path
) -> None:
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    path = tmp_path / "key.pem"
    path.write_bytes(
        private.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    calls = []

    def post(route: str, body: dict[str, str]) -> dict[str, object]:
        calls.append(route)
        return dict(fields)

    with pytest.raises(TimeBaseOperationError, match="invalid response"):
        WebAdminSession.acquire("reader", str(path), post)
    assert calls == ["/attempt"]
