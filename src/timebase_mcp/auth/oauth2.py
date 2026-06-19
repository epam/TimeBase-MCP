from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import json
import time
from typing import Any, Protocol
from urllib import error, parse, request

TOKEN_REQUEST_TIMEOUT_SECONDS = 30
TOKEN_EXPIRY_SKEW_SECONDS = 30.0
OAUTH2_RESERVED_PARAMS = {
    "grant_type",
    "client_id",
    "client_secret",
    "scope",
}


@dataclass(frozen=True)
class OAuth2ClientCredentialsConfig:
    token_url: str
    client_id: str
    client_secret: str
    scope: str | None = None
    token_params: dict[str, str] | None = None


@dataclass(frozen=True)
class _CachedAccessToken:
    access_token: str
    expires_at_monotonic: float | None


@dataclass(frozen=True)
class TokenResponse:
    access_token: str
    refresh_token: str | None = None
    expires_at_monotonic: float | None = None
    payload: dict[str, Any] | None = None


class OAuth2AccessTokenProvider(Protocol):
    def get_access_token(self) -> str:
        """Return an OAuth2 access token."""
        ...


def token_has_expired(
    expires_at_monotonic: float | None,
    *,
    monotonic: Callable[[], float],
) -> bool:
    if expires_at_monotonic is None:
        return False

    return monotonic() >= expires_at_monotonic - TOKEN_EXPIRY_SKEW_SECONDS


def parse_token_response(
    token_response: object,
    *,
    monotonic: Callable[[], float],
    access_token_error: str,
) -> TokenResponse:
    if not isinstance(token_response, dict):
        raise ValueError("OAuth2 token response must be a JSON object.")

    access_token = token_response.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        raise ValueError(access_token_error)

    refresh_token_value = token_response.get("refresh_token")
    refresh_token = (
        refresh_token_value
        if isinstance(refresh_token_value, str) and refresh_token_value
        else None
    )

    expires_in_seconds = parse_expires_in(token_response.get("expires_in"))
    expires_at_monotonic = None
    if expires_in_seconds is not None:
        expires_at_monotonic = monotonic() + expires_in_seconds

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_at_monotonic=expires_at_monotonic,
        payload=token_response,
    )


def parse_expires_in(value: object) -> float | None:
    if value is None:
        return None

    if isinstance(value, int | float):
        expires_in_seconds = float(value)
    elif isinstance(value, str):
        try:
            expires_in_seconds = float(value)
        except ValueError as exc:
            raise ValueError(
                "OAuth2 token response contains a non-numeric expires_in value."
            ) from exc
    else:
        raise ValueError("OAuth2 token response contains an invalid expires_in value.")

    if expires_in_seconds <= 0:
        raise ValueError(
            "OAuth2 token response must include a positive expires_in value when present."
        )

    return expires_in_seconds


def build_token_request_fields(
    base_fields: dict[str, str],
    *,
    extra_fields: dict[str, str] | None = None,
    reserved_params_error_prefix: str,
) -> dict[str, str]:
    token_request_fields = dict(base_fields)
    extra_token_params = extra_fields or {}
    conflicting_params = sorted(
        name for name in extra_token_params if name in OAUTH2_RESERVED_PARAMS
    )
    if conflicting_params:
        raise ValueError(
            reserved_params_error_prefix
            + " cannot override reserved OAuth2 fields: "
            + ", ".join(conflicting_params)
            + "."
        )

    token_request_fields.update(extra_token_params)
    return token_request_fields


class UrlLibTokenEndpointClient:
    def __init__(
        self,
        *,
        urlopen: Callable[..., Any] = request.urlopen,
        timeout_seconds: int = TOKEN_REQUEST_TIMEOUT_SECONDS,
    ) -> None:
        self._urlopen = urlopen
        self._timeout_seconds = timeout_seconds

    def post_form(self, token_url: str, fields: dict[str, str]) -> dict[str, Any]:
        encoded_request_body = parse.urlencode(fields).encode("utf-8")
        token_request = request.Request(
            url=token_url,
            data=encoded_request_body,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            method="POST",
        )

        try:
            with self._urlopen(
                token_request, timeout=self._timeout_seconds
            ) as response:
                response_body = response.read().decode("utf-8")
        except error.HTTPError as exc:
            message = (
                f"OAuth2 token request failed with HTTP {exc.code}: "
                f"{read_http_error_response(exc)}"
            )
            if exc.code in {400, 401, 403}:
                raise PermissionError(message) from exc
            raise ConnectionError(message) from exc
        except TimeoutError as exc:
            raise ConnectionError("OAuth2 token request timed out.") from exc
        except error.URLError as exc:
            raise ConnectionError(f"OAuth2 token request failed: {exc.reason}") from exc

        return parse_json_token_response(response_body)


def parse_json_token_response(response_body: str) -> dict[str, Any]:
    try:
        token_response = json.loads(response_body)
    except json.JSONDecodeError as exc:
        raise ValueError("OAuth2 token response was not valid JSON.") from exc

    if not isinstance(token_response, dict):
        raise ValueError("OAuth2 token response must be a JSON object.")
    return token_response


def read_http_error_response(exc: error.HTTPError) -> str:
    response_body = exc.read().decode("utf-8", errors="replace").strip()
    if not response_body:
        return exc.reason

    try:
        error_payload = json.loads(response_body)
    except json.JSONDecodeError:
        return response_body

    if isinstance(error_payload, dict):
        for key in ("error_description", "error", "message"):
            detail = error_payload.get(key)
            if isinstance(detail, str) and detail:
                return detail

    return response_body


class OAuth2ClientCredentialsProvider:
    def __init__(
        self,
        config: OAuth2ClientCredentialsConfig,
        *,
        urlopen: Callable[..., Any] = request.urlopen,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._config = config
        self._token_endpoint = UrlLibTokenEndpointClient(urlopen=urlopen)
        self._monotonic = monotonic
        self._cached_token: _CachedAccessToken | None = None

    def get_access_token(self) -> str:
        if self._cached_token is not None and not self._token_has_expired(
            self._cached_token
        ):
            return self._cached_token.access_token

        cached_token = self._request_access_token()
        self._cached_token = cached_token
        return cached_token.access_token

    def _request_access_token(self) -> _CachedAccessToken:
        base_fields = {
            "grant_type": "client_credentials",
            "client_id": self._config.client_id,
            "client_secret": self._config.client_secret,
        }
        if self._config.scope is not None:
            base_fields["scope"] = self._config.scope

        token_request_fields = build_token_request_fields(
            base_fields,
            extra_fields=self._config.token_params,
            reserved_params_error_prefix="TIMEBASE_OAUTH2_TOKEN_PARAMS",
        )
        token_response = parse_token_response(
            self._token_endpoint.post_form(
                self._config.token_url, token_request_fields
            ),
            monotonic=self._monotonic,
            access_token_error=(
                "OAuth2 token response did not include a valid access_token."
            ),
        )

        return _CachedAccessToken(
            access_token=token_response.access_token,
            expires_at_monotonic=token_response.expires_at_monotonic,
        )

    def _token_has_expired(self, token: _CachedAccessToken) -> bool:
        return token_has_expired(token.expires_at_monotonic, monotonic=self._monotonic)


def get_oauth2_access_token(
    config: OAuth2ClientCredentialsConfig,
    *,
    provider: OAuth2AccessTokenProvider | None = None,
) -> str:
    return get_oauth2_provider(config, provider=provider).get_access_token()


def get_oauth2_provider(
    config: OAuth2ClientCredentialsConfig,
    *,
    provider: OAuth2AccessTokenProvider | None = None,
) -> OAuth2AccessTokenProvider:
    if provider is None:
        provider = OAuth2ClientCredentialsProvider(config)

    return provider
