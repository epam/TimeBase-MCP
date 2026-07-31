from __future__ import annotations

from typing import Any

import httpx2


def response_json_dict(
    response: httpx2.Response,
    *,
    error_factory: type[Exception] = ValueError,
    what: str = "response",
) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise error_factory(f"Expected JSON response from {what}.") from exc
    if not isinstance(payload, dict):
        raise error_factory(f"Unexpected response from {what}.")
    return payload


def response_json_list(
    response: httpx2.Response,
    *,
    error_factory: type[Exception] = ValueError,
    what: str = "response",
) -> list[dict[str, Any]]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise error_factory(f"Expected JSON response from {what}.") from exc
    if not isinstance(payload, list):
        raise error_factory(f"Unexpected response from {what}.")
    return [item for item in payload if isinstance(item, dict)]
