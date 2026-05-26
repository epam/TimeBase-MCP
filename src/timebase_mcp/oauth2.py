from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import json
import time
from typing import Any, Protocol
from urllib import error, parse, request

_TOKEN_REQUEST_TIMEOUT_SECONDS = 30
_TOKEN_EXPIRY_SKEW_SECONDS = 30.0
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


class OAuth2AccessTokenProvider(Protocol):
    def get_access_token(self) -> str:
        """Return an OAuth2 access token."""
        ...


class OAuth2ClientCredentialsProvider:
    def __init__(
        self,
        config: OAuth2ClientCredentialsConfig,
        *,
        urlopen: Callable[..., Any] = request.urlopen,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._config = config
        self._urlopen = urlopen
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
        token_request_fields = {
            "grant_type": "client_credentials",
            "client_id": self._config.client_id,
            "client_secret": self._config.client_secret,
        }
        if self._config.scope is not None:
            token_request_fields["scope"] = self._config.scope

        extra_token_params = self._config.token_params or {}
        conflicting_params = sorted(
            name for name in extra_token_params if name in OAUTH2_RESERVED_PARAMS
        )
        if conflicting_params:
            raise ValueError(
                "TIMEBASE_OAUTH2_TOKEN_PARAMS cannot override reserved OAuth2 fields: "
                + ", ".join(conflicting_params)
                + "."
            )

        token_request_fields.update(extra_token_params)
        encoded_request_body = parse.urlencode(token_request_fields).encode("utf-8")
        token_request = request.Request(
            url=self._config.token_url,
            data=encoded_request_body,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            method="POST",
        )

        try:
            with self._urlopen(
                token_request, timeout=_TOKEN_REQUEST_TIMEOUT_SECONDS
            ) as response:
                response_body = response.read().decode("utf-8")
        except error.HTTPError as exc:
            message = (
                f"OAuth2 token request failed with HTTP {exc.code}: "
                f"{self._read_error_response(exc)}"
            )
            if exc.code in {400, 401, 403}:
                raise PermissionError(message) from exc
            raise ConnectionError(message) from exc
        except TimeoutError as exc:
            raise ConnectionError("OAuth2 token request timed out.") from exc
        except error.URLError as exc:
            raise ConnectionError(f"OAuth2 token request failed: {exc.reason}") from exc

        try:
            token_response = json.loads(response_body)
        except json.JSONDecodeError as exc:
            raise ValueError("OAuth2 token response was not valid JSON.") from exc

        if not isinstance(token_response, dict):
            raise ValueError("OAuth2 token response must be a JSON object.")

        access_token = token_response.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise ValueError(
                "OAuth2 token response did not include a valid access_token."
            )

        expires_in_seconds = self._parse_expires_in(token_response.get("expires_in"))
        expires_at_monotonic = None
        if expires_in_seconds is not None:
            expires_at_monotonic = self._monotonic() + expires_in_seconds

        return _CachedAccessToken(
            access_token=access_token,
            expires_at_monotonic=expires_at_monotonic,
        )

    def _token_has_expired(self, token: _CachedAccessToken) -> bool:
        if token.expires_at_monotonic is None:
            return False

        return (
            self._monotonic() >= token.expires_at_monotonic - _TOKEN_EXPIRY_SKEW_SECONDS
        )

    @staticmethod
    def _parse_expires_in(value: object) -> float | None:
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
            raise ValueError(
                "OAuth2 token response contains an invalid expires_in value."
            )

        if expires_in_seconds <= 0:
            raise ValueError(
                "OAuth2 token response must include a positive expires_in value when present."
            )

        return expires_in_seconds

    @staticmethod
    def _read_error_response(exc: error.HTTPError) -> str:
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
