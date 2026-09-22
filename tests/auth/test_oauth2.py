import io
import json
from email.message import Message
from unittest.mock import Mock
from urllib import error, parse
from urllib.response import addinfourl

import pytest

from timebase_mcp.auth.oauth2 import (
    OAuth2ClientCredentialsConfig,
    OAuth2ClientCredentialsProvider,
    OAuth2PasswordConfig,
    OAuth2PasswordProvider,
    UrlLibTokenEndpointClient,
    get_oauth2_access_token,
    get_oauth2_provider,
    parse_expires_in,
    parse_token_response,
)


def token_response(
    payload: dict[str, object] | bytes, *, status: int = 200
) -> addinfourl:
    if isinstance(payload, dict):
        payload = json.dumps(payload).encode("utf-8")
    return addinfourl(
        io.BytesIO(payload), Message(), "https://idp.example/token", code=status
    )


class Clock:
    def __init__(self, current: float) -> None:
        self.current = current

    def __call__(self) -> float:
        return self.current


@pytest.mark.parametrize("value", [True, float("nan"), float("inf"), "NaN", "Infinity"])
def test_token_expiry_rejects_nonfinite_values(value: object) -> None:
    with pytest.raises(ValueError):
        parse_expires_in(value)


def test_token_response_size_is_bounded() -> None:
    client = UrlLibTokenEndpointClient(
        urlopen=lambda *args, **kwargs: token_response(b"x" * 200000)
    )
    with pytest.raises(ValueError, match="response limit"):
        client.post_form("https://idp.example/token", {"grant_type": "password"})


@pytest.mark.parametrize("mode", ["password", "client_credentials"])
@pytest.mark.parametrize("status", [201, 202, 204, 206])
def test_token_provider_rejects_non_200_before_reading_or_caching(
    monkeypatch, mode, status
):
    rejected = token_response({"access_token": "private-token"}, status=status)
    read = Mock(wraps=rejected.read)
    monkeypatch.setattr(rejected, "read", read)
    accepted = token_response({"access_token": "valid-token", "expires_in": 3600})
    responses = [rejected, accepted]

    def urlopen(*args, **kwargs):
        return responses.pop(0)

    if mode == "password":
        provider = OAuth2PasswordProvider(
            OAuth2PasswordConfig(
                token_url="https://idp.example/token",
                username="user",
                password="secret",
                client_id="client-id",
                client_secret="client-secret",
            ),
            urlopen=urlopen,
        )
    else:
        provider = OAuth2ClientCredentialsProvider(
            build_oauth2_config(), urlopen=urlopen
        )

    with pytest.raises(
        ConnectionError, match=f"HTTP {status}.*expected HTTP 200"
    ) as exc:
        provider.get_access_token()
    assert "private-token" not in str(exc.value)
    assert rejected.closed
    read.assert_not_called()
    assert provider.get_access_token() == "valid-token"
    assert provider.get_access_token() == "valid-token"
    assert accepted.closed
    assert not responses


def build_oauth2_config(**overrides: object) -> OAuth2ClientCredentialsConfig:
    token_url = overrides.pop("token_url", "https://idp.example/token")
    client_id = overrides.pop("client_id", "client-id")
    client_secret = overrides.pop("client_secret", "client-secret")
    scope = overrides.pop("scope", "timebase.read timebase.write")
    token_params = overrides.pop("token_params", {"audience": "timebase-api"})
    if overrides:
        unexpected_keys = ", ".join(sorted(str(key) for key in overrides))
        raise AssertionError(f"Unexpected overrides: {unexpected_keys}")

    assert isinstance(token_url, str)
    assert isinstance(client_id, str)
    assert isinstance(client_secret, str)
    assert isinstance(scope, str | type(None))
    assert isinstance(token_params, dict | type(None))

    return OAuth2ClientCredentialsConfig(
        token_url=token_url,
        client_id=client_id,
        client_secret=client_secret,
        scope=scope,
        token_params=token_params,
    )


def test_oauth2_provider_posts_expected_token_request() -> None:
    captured_request: dict[str, object] = {}

    def fake_urlopen(request_obj, timeout: int):
        captured_request["url"] = request_obj.full_url
        captured_request["headers"] = {
            key.lower(): value for key, value in request_obj.header_items()
        }
        captured_request["body"] = request_obj.data.decode("utf-8")
        captured_request["timeout"] = timeout
        return token_response({"access_token": "token-1", "expires_in": 120})

    provider = OAuth2ClientCredentialsProvider(
        build_oauth2_config(),
        urlopen=fake_urlopen,
        monotonic=Clock(100.0),
    )

    access_token = provider.get_access_token()

    assert access_token == "token-1"
    assert captured_request["url"] == "https://idp.example/token"
    assert captured_request["headers"] == {
        "accept": "application/json",
        "content-type": "application/x-www-form-urlencoded",
    }
    assert captured_request["timeout"] == 30
    assert parse.parse_qs(str(captured_request["body"])) == {
        "grant_type": ["client_credentials"],
        "client_id": ["client-id"],
        "client_secret": ["client-secret"],
        "scope": ["timebase.read timebase.write"],
        "audience": ["timebase-api"],
    }


def test_oauth2_password_provider_posts_expected_cached_token_request() -> None:
    captured_bodies: list[str] = []
    captured_headers: dict[str, str] = {}

    def fake_urlopen(request_obj, timeout: int):
        assert request_obj.full_url == "http://localhost:8099/oauth/token"
        assert timeout == 30
        captured_bodies.append(request_obj.data.decode("utf-8"))
        captured_headers.update(
            {key.lower(): value for key, value in request_obj.header_items()}
        )
        return token_response({"access_token": "token-1", "expires_in": 120})

    provider = OAuth2PasswordProvider(
        OAuth2PasswordConfig(
            token_url="http://localhost:8099/oauth/token",
            username="admin",
            password="secret",
            client_id="client-id",
            client_secret="client-secret",
        ),
        urlopen=fake_urlopen,
        monotonic=Clock(100.0),
    )

    assert provider.get_access_token() == "token-1"
    assert provider.get_access_token() == "token-1"
    assert len(captured_bodies) == 1
    assert captured_headers["authorization"] == "Basic Y2xpZW50LWlkOmNsaWVudC1zZWNyZXQ="
    assert parse.parse_qs(captured_bodies[0]) == {
        "grant_type": ["password"],
        "username": ["admin"],
        "password": ["secret"],
    }


@pytest.mark.parametrize("mode", ["password", "client_credentials"])
def test_token_provider_reuses_then_reacquires_at_expiry(mode):
    clock = Clock(100.0)
    responses = [
        token_response({"access_token": "first", "expires_in": 60}),
        token_response({"access_token": "second", "expires_in": 60}),
    ]

    def urlopen(*args, **kwargs):
        return responses.pop(0)

    if mode == "password":
        provider = OAuth2PasswordProvider(
            OAuth2PasswordConfig(
                token_url="https://idp.example/token",
                username="user",
                password="password",
                client_id="client",
                client_secret="secret",
            ),
            urlopen=urlopen,
            monotonic=clock,
        )
    else:
        provider = OAuth2ClientCredentialsProvider(
            build_oauth2_config(),
            urlopen=urlopen,
            monotonic=clock,
        )
    assert provider.get_access_token() == "first"
    clock.current = 129.0
    assert provider.get_access_token() == "first"
    clock.current = 130.0
    assert provider.get_access_token() == "second"
    assert provider.get_access_token() == "second"
    assert not responses


def test_oauth2_provider_raises_for_http_error() -> None:
    def fake_urlopen(request_obj, timeout: int):
        del request_obj, timeout
        raise error.HTTPError(
            url="https://idp.example/token",
            code=401,
            msg="Unauthorized",
            hdrs=Message(),
            fp=io.BytesIO(b'{"error_description": "private-server-detail"}'),
        )

    provider = OAuth2ClientCredentialsProvider(
        build_oauth2_config(),
        urlopen=fake_urlopen,
    )

    with pytest.raises(PermissionError, match="HTTP 401") as exc:
        provider.get_access_token()
    assert "private-server-detail" not in str(exc.value)


@pytest.mark.parametrize("status_code", [400, 401, 403])
def test_oauth2_password_provider_maps_token_authorization_errors(
    status_code: int,
) -> None:
    provider = OAuth2PasswordProvider(
        OAuth2PasswordConfig(
            token_url="https://idp.example/token",
            username="admin",
            password="secret",
            client_id="client-id",
            client_secret="client-secret",
        ),
        urlopen=lambda request_obj, timeout: (_ for _ in ()).throw(
            error.HTTPError(
                url="https://idp.example/token",
                code=status_code,
                msg="Denied",
                hdrs=Message(),
                fp=io.BytesIO(b'{"error_description": "token denied"}'),
            )
        ),
    )

    with pytest.raises(PermissionError, match=rf"HTTP {status_code}"):
        provider.get_access_token()


def test_oauth2_provider_rejects_reserved_token_params() -> None:
    provider = OAuth2ClientCredentialsProvider(
        build_oauth2_config(token_params={"scope": "override"}),
        urlopen=lambda request_obj, timeout: token_response(
            {"access_token": "unused", "expires_in": 120}
        ),
    )

    with pytest.raises(ValueError, match="cannot override reserved"):
        provider.get_access_token()


def test_get_oauth2_provider_creates_default_provider() -> None:
    provider = get_oauth2_provider(build_oauth2_config())

    assert isinstance(provider, OAuth2ClientCredentialsProvider)


def test_get_oauth2_provider_reuses_passed_provider() -> None:
    provider = OAuth2ClientCredentialsProvider(build_oauth2_config())

    assert get_oauth2_provider(build_oauth2_config(), provider=provider) is provider


def test_get_oauth2_access_token_uses_passed_provider() -> None:
    provider = OAuth2ClientCredentialsProvider(
        build_oauth2_config(),
        urlopen=lambda request_obj, timeout: token_response(
            {"access_token": "token-1", "expires_in": 120}
        ),
    )

    assert (
        get_oauth2_access_token(build_oauth2_config(), provider=provider) == "token-1"
    )


def test_oauth2_provider_raises_for_timeout() -> None:
    provider = OAuth2ClientCredentialsProvider(
        build_oauth2_config(),
        urlopen=lambda request_obj, timeout: (_ for _ in ()).throw(TimeoutError()),
    )

    with pytest.raises(ConnectionError, match="timed out"):
        provider.get_access_token()


def test_oauth2_provider_raises_for_url_error() -> None:
    provider = OAuth2ClientCredentialsProvider(
        build_oauth2_config(),
        urlopen=lambda request_obj, timeout: (_ for _ in ()).throw(
            error.URLError("connection refused")
        ),
    )

    with pytest.raises(ConnectionError, match="endpoint unavailable"):
        provider.get_access_token()


def test_oauth2_provider_raises_for_invalid_json_response() -> None:
    provider = OAuth2ClientCredentialsProvider(
        build_oauth2_config(),
        urlopen=lambda request_obj, timeout: token_response(b"not-json"),
    )

    with pytest.raises(ValueError, match="not valid JSON"):
        provider.get_access_token()


def test_oauth2_provider_raises_for_non_object_json_response() -> None:
    provider = OAuth2ClientCredentialsProvider(
        build_oauth2_config(),
        urlopen=lambda request_obj, timeout: token_response(b'["not-an-object"]'),
    )

    with pytest.raises(ValueError, match="must be a JSON object"):
        provider.get_access_token()


def test_oauth2_provider_raises_for_missing_access_token() -> None:
    provider = OAuth2ClientCredentialsProvider(
        build_oauth2_config(),
        urlopen=lambda request_obj, timeout: token_response({"expires_in": 120}),
    )

    with pytest.raises(ValueError, match="valid access_token"):
        provider.get_access_token()


def test_oauth2_provider_raises_for_invalid_expires_in() -> None:
    provider = OAuth2ClientCredentialsProvider(
        build_oauth2_config(),
        urlopen=lambda request_obj, timeout: token_response(
            {"access_token": "token-1", "expires_in": "not-a-number"}
        ),
    )

    with pytest.raises(ValueError, match="non-numeric expires_in"):
        provider.get_access_token()


def test_shared_token_parser_returns_refresh_token_and_expiry() -> None:
    parsed = parse_token_response(
        {"access_token": "token-1", "refresh_token": "refresh-1", "expires_in": 120},
        monotonic=Clock(100.0),
        access_token_error="missing token",
    )

    assert parsed.access_token == "token-1"
    assert parsed.refresh_token == "refresh-1"
    assert parsed.expires_at_monotonic == 220.0


def test_token_endpoint_client_posts_form_with_content_type() -> None:
    captured_request: dict[str, object] = {}

    def fake_urlopen(request_obj, timeout: int):
        captured_request["headers"] = {
            key.lower(): value for key, value in request_obj.header_items()
        }
        captured_request["body"] = request_obj.data.decode("utf-8")
        captured_request["timeout"] = timeout
        return token_response({"access_token": "token-1"})

    client = UrlLibTokenEndpointClient(urlopen=fake_urlopen)
    payload = client.post_form(
        "https://idp.example/token",
        {"grant_type": "refresh_token", "refresh_token": "refresh-1"},
    )

    assert payload == {"access_token": "token-1"}
    assert captured_request["headers"] == {
        "accept": "application/json",
        "content-type": "application/x-www-form-urlencoded",
    }
    assert captured_request["timeout"] == 30
    assert parse.parse_qs(str(captured_request["body"])) == {
        "grant_type": ["refresh_token"],
        "refresh_token": ["refresh-1"],
    }
