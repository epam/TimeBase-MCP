from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from locust.clients import HttpSession

from tests.support.mcp_http import (
    build_client_meta,
    build_modern_headers,
    parse_jsonrpc_response,
)

_MAX_TOOL_ERROR_TEXT = 500
_CLIENT_INFO_NAME = "timebase-mcp-stress"
_CLIENT_INFO_VERSION = "0.1.0"


class McpProtocolError(RuntimeError):
    pass


@dataclass(slots=True)
class McpResponse:
    payload: dict[str, Any] | None
    status_code: int

    @property
    def error_message(self) -> str | None:
        if self.payload is None:
            return None
        error = self.payload.get("error")
        if isinstance(error, dict):
            message = error.get("message")
            return str(message) if message is not None else str(error)
        return None


class StreamableHttpMcpClient:
    def __init__(self, http: HttpSession, *, path: str = "/mcp") -> None:
        self._http = http
        self._path = path
        self._next_id = 1

    def discover(self) -> McpResponse:
        return self._request(
            "mcp:discover",
            method="server/discover",
            params={},
        )

    def close(self) -> None:
        # Sessionless modern transport has nothing to terminate.
        return

    def call_tool(
        self, name: str, arguments: dict[str, Any] | None = None
    ) -> McpResponse:
        return self._request(
            f"tool:{name}",
            method="tools/call",
            params={
                "name": name,
                "arguments": arguments or {},
            },
            mcp_name=name,
        )

    def _request(
        self,
        name: str,
        *,
        method: str,
        params: dict[str, Any],
        mcp_name: str | None = None,
        expect_response: bool = True,
    ) -> McpResponse:
        body_params = dict(params)
        body_params["_meta"] = build_client_meta(
            client_name=_CLIENT_INFO_NAME,
            client_version=_CLIENT_INFO_VERSION,
        )
        payload: dict[str, Any] = {
            "jsonrpc": "2.0",
            "method": method,
            "params": body_params,
        }
        if expect_response:
            payload["id"] = self._request_id()

        headers = build_modern_headers(method=method, mcp_name=mcp_name)
        with self._http.post(
            self._path,
            json=payload,
            headers=headers,
            name=name,
            catch_response=True,
        ) as response:
            if response.status_code == 202 and not expect_response:
                response.success()
                return McpResponse(payload=None, status_code=response.status_code)

            if response.status_code >= 400:
                response.failure(f"HTTP {response.status_code}: {response.text[:500]}")
                return McpResponse(payload=None, status_code=response.status_code)

            if response.headers.get("mcp-session-id"):
                response.failure(
                    "Unexpected Mcp-Session-Id on 2026-07-28 sessionless response"
                )
                return McpResponse(payload=None, status_code=response.status_code)

            try:
                message = parse_jsonrpc_response(response)
            except Exception as exc:  # noqa: BLE001 - reported as a locust failure
                response.failure(str(exc))
                return McpResponse(payload=None, status_code=response.status_code)

            if message is None:
                if expect_response:
                    response.failure("Expected JSON-RPC response body")
                else:
                    response.success()
                return McpResponse(payload=None, status_code=response.status_code)

            error = message.get("error")
            if isinstance(error, dict):
                response.failure(str(error.get("message") or error))
            elif _is_tool_error(message):
                response.failure(_format_tool_error(message))
            else:
                response.success()
            return McpResponse(payload=message, status_code=response.status_code)

        raise McpProtocolError("request completed without MCP response")

    def _request_id(self) -> int:
        request_id = self._next_id
        self._next_id += 1
        return request_id


def _is_tool_error(message: dict[str, Any]) -> bool:
    result = message.get("result")
    return isinstance(result, dict) and (
        result.get("isError") is True or result.get("is_error") is True
    )


def _format_tool_error(message: dict[str, Any]) -> str:
    result = message.get("result")
    if not isinstance(result, dict):
        return "MCP tool error: result payload is not an object"

    texts: list[str] = []
    content = result.get("content")
    if isinstance(content, list):
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "text":
                continue
            text = block.get("text")
            if isinstance(text, str):
                stripped = text.strip()
                if stripped:
                    texts.append(stripped)

    if texts:
        combined = "; ".join(texts)
        if len(combined) > _MAX_TOOL_ERROR_TEXT:
            return combined[: _MAX_TOOL_ERROR_TEXT - 3] + "..."
        return combined

    structured = result.get("structuredContent")
    if structured is None:
        structured = result.get("structured_content")
    if structured is not None:
        try:
            serialized = json.dumps(structured, ensure_ascii=False)
        except (TypeError, ValueError):
            serialized = str(structured)
        return _truncate(serialized)

    return f"MCP tool error result: {_truncate(json.dumps(result, ensure_ascii=False))}"


def _truncate(value: str) -> str:
    if len(value) > _MAX_TOOL_ERROR_TEXT:
        return value[: _MAX_TOOL_ERROR_TEXT - 3] + "..."
    return value
