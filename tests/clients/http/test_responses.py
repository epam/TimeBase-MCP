from __future__ import annotations

import httpx2
import pytest

from timebase_mcp.clients.http.responses import response_json_dict, response_json_list
from timebase_mcp.errors import ConfigurationError


def _response(content: bytes | str, *, status_code: int = 200) -> httpx2.Response:
    if isinstance(content, str):
        content = content.encode("utf-8")
    return httpx2.Response(status_code, content=content)


def test_response_json_dict_returns_object() -> None:
    assert response_json_dict(_response('{"a": 1}')) == {"a": 1}


def test_response_json_list_keeps_only_dict_items() -> None:
    payload = '[{"a": 1}, "x", 1, {"b": 2}]'
    assert response_json_list(_response(payload)) == [{"a": 1}, {"b": 2}]


def test_response_json_dict_rejects_non_json() -> None:
    with pytest.raises(ValueError, match="Expected JSON response from oauthinfo"):
        response_json_dict(_response("not-json"), what="oauthinfo")


def test_response_json_list_rejects_non_json() -> None:
    with pytest.raises(ValueError, match="Expected JSON response from monitors"):
        response_json_list(_response("not-json"), what="monitors")


def test_response_json_dict_rejects_non_object() -> None:
    with pytest.raises(ValueError, match="Unexpected response from oauthinfo"):
        response_json_dict(_response("[1, 2]"), what="oauthinfo")


def test_response_json_list_rejects_non_list() -> None:
    with pytest.raises(ValueError, match="Unexpected response from monitors"):
        response_json_list(_response('{"a": 1}'), what="monitors")


def test_response_json_helpers_use_custom_error_factory() -> None:
    with pytest.raises(ConfigurationError, match="Expected JSON response from oauth"):
        response_json_dict(
            _response("oops"),
            error_factory=ConfigurationError,
            what="oauth",
        )

    with pytest.raises(ConfigurationError, match="Unexpected response from oauth"):
        response_json_dict(
            _response("[1]"),
            error_factory=ConfigurationError,
            what="oauth",
        )

    with pytest.raises(ConfigurationError, match="Expected JSON response from rows"):
        response_json_list(
            _response("oops"),
            error_factory=ConfigurationError,
            what="rows",
        )

    with pytest.raises(ConfigurationError, match="Unexpected response from rows"):
        response_json_list(
            _response('{"a": 1}'),
            error_factory=ConfigurationError,
            what="rows",
        )
