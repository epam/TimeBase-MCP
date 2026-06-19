from email.message import Message
import io
import json
from urllib import error, parse

import pytest

from timebase_mcp.auth.oauth2 import (
    OAuth2ClientCredentialsConfig,
    OAuth2ClientCredentialsProvider,
    UrlLibTokenEndpointClient,
    get_oauth2_access_token,
    get_oauth2_provider,
    parse_token_response,
)


class DummyResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._payload

    def __enter__(self) -> "DummyResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


class RawResponse:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return self._payload

    def __enter__(self) -> "RawResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


class Clock:
    def __init__(self, current: float) -> None:
        self.current = current

    def __call__(self) -> float:
        return self.current


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
        return DummyResponse({"access_token": "token-1", "expires_in": 120})

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


def test_oauth2_provider_reuses_cached_token_until_expiry() -> None:
    response_count = 0
    clock = Clock(100.0)

    def fake_urlopen(request_obj, timeout: int):
        del request_obj, timeout
        nonlocal response_count
        response_count += 1
        return DummyResponse(
            {"access_token": f"token-{response_count}", "expires_in": 120}
        )

    provider = OAuth2ClientCredentialsProvider(
        build_oauth2_config(),
        urlopen=fake_urlopen,
        monotonic=clock,
    )

    first_access_token = provider.get_access_token()
    clock.current = 150.0
    second_access_token = provider.get_access_token()

    assert first_access_token == "token-1"
    assert second_access_token == "token-1"
    assert response_count == 1


def test_oauth2_provider_refreshes_expired_token() -> None:
    response_count = 0
    clock = Clock(100.0)

    def fake_urlopen(request_obj, timeout: int):
        del request_obj, timeout
        nonlocal response_count
        response_count += 1
        return DummyResponse(
            {"access_token": f"token-{response_count}", "expires_in": 60}
        )

    provider = OAuth2ClientCredentialsProvider(
        build_oauth2_config(),
        urlopen=fake_urlopen,
        monotonic=clock,
    )

    first_access_token = provider.get_access_token()
    clock.current = 131.0
    second_access_token = provider.get_access_token()

    assert first_access_token == "token-1"
    assert second_access_token == "token-2"
    assert response_count == 2


def test_oauth2_provider_raises_for_http_error() -> None:
    def fake_urlopen(request_obj, timeout: int):
        del request_obj, timeout
        raise error.HTTPError(
            url="https://idp.example/token",
            code=401,
            msg="Unauthorized",
            hdrs=Message(),
            fp=io.BytesIO(b'{"error_description": "invalid client"}'),
        )

    provider = OAuth2ClientCredentialsProvider(
        build_oauth2_config(),
        urlopen=fake_urlopen,
    )

    with pytest.raises(PermissionError, match="HTTP 401: invalid client"):
        provider.get_access_token()


def test_oauth2_provider_rejects_reserved_token_params() -> None:
    provider = OAuth2ClientCredentialsProvider(
        build_oauth2_config(token_params={"scope": "override"}),
        urlopen=lambda request_obj, timeout: DummyResponse(
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
        urlopen=lambda request_obj, timeout: DummyResponse(
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

    with pytest.raises(ConnectionError, match="connection refused"):
        provider.get_access_token()


def test_oauth2_provider_raises_for_invalid_json_response() -> None:
    provider = OAuth2ClientCredentialsProvider(
        build_oauth2_config(),
        urlopen=lambda request_obj, timeout: RawResponse(b"not-json"),
    )

    with pytest.raises(ValueError, match="not valid JSON"):
        provider.get_access_token()


def test_oauth2_provider_raises_for_non_object_json_response() -> None:
    provider = OAuth2ClientCredentialsProvider(
        build_oauth2_config(),
        urlopen=lambda request_obj, timeout: RawResponse(b'["not-an-object"]'),
    )

    with pytest.raises(ValueError, match="must be a JSON object"):
        provider.get_access_token()


def test_oauth2_provider_raises_for_missing_access_token() -> None:
    provider = OAuth2ClientCredentialsProvider(
        build_oauth2_config(),
        urlopen=lambda request_obj, timeout: DummyResponse({"expires_in": 120}),
    )

    with pytest.raises(ValueError, match="valid access_token"):
        provider.get_access_token()


def test_oauth2_provider_raises_for_invalid_expires_in() -> None:
    provider = OAuth2ClientCredentialsProvider(
        build_oauth2_config(),
        urlopen=lambda request_obj, timeout: DummyResponse(
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
        return DummyResponse({"access_token": "token-1"})

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
