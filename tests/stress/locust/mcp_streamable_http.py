from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from locust.clients import HttpSession

JSON = "application/json"
SSE = "text/event-stream"
PROTOCOL_VERSION = "2025-06-18"
_MAX_TOOL_ERROR_TEXT = 500


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
        self._session_id: str | None = None
        self._protocol_version: str | None = None

    def initialize(self) -> McpResponse:
        payload = self._request(
            "mcp:initialize",
            {
                "jsonrpc": "2.0",
                "id": self._request_id(),
                "method": "initialize",
                "params": {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {
                        "name": "timebase-mcp-locust",
                        "version": "0.1.0",
                    },
                },
            },
            include_session=False,
        )

        if payload.payload is None:
            raise McpProtocolError("initialize returned no JSON-RPC payload")

        result = payload.payload.get("result")
        if isinstance(result, dict):
            protocol_version = result.get("protocolVersion")
            if isinstance(protocol_version, str):
                self._protocol_version = protocol_version

        self.notify("notifications/initialized", name="mcp:initialized")
        return payload

    def close(self) -> None:
        if self._session_id is None:
            return
        headers = self._headers(include_session=True)
        with self._http.delete(
            self._path,
            headers=headers,
            name="mcp:terminate",
            catch_response=True,
        ) as response:
            if response.status_code in (200, 202, 204, 404):
                response.success()
            else:
                response.failure(f"Unexpected terminate status: {response.status_code}")
        self._session_id = None

    def call_tool(
        self, name: str, arguments: dict[str, Any] | None = None
    ) -> McpResponse:
        return self._request(
            f"tool:{name}",
            {
                "jsonrpc": "2.0",
                "id": self._request_id(),
                "method": "tools/call",
                "params": {
                    "name": name,
                    "arguments": arguments or {},
                },
            },
        )

    def notify(
        self, method: str, *, name: str, params: dict[str, Any] | None = None
    ) -> None:
        self._request(
            name,
            {
                "jsonrpc": "2.0",
                "method": method,
                "params": params or {},
            },
            expect_response=False,
        )

    def _request(
        self,
        name: str,
        payload: dict[str, Any],
        *,
        include_session: bool = True,
        expect_response: bool = True,
    ) -> McpResponse:
        headers = self._headers(include_session=include_session)
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

            session_id = response.headers.get("mcp-session-id")
            if session_id:
                self._session_id = session_id

            try:
                message = self._parse_response(response)
            except Exception as exc:
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

    def _headers(self, *, include_session: bool) -> dict[str, str]:
        headers = {
            "accept": f"{JSON}, {SSE}",
            "content-type": JSON,
        }
        if include_session and self._session_id:
            headers["mcp-session-id"] = self._session_id
        if self._protocol_version:
            headers["mcp-protocol-version"] = self._protocol_version
        return headers

    def _parse_response(self, response) -> dict[str, Any] | None:
        content_type = response.headers.get("content-type", "").lower()
        if content_type.startswith(JSON):
            return response.json()
        if content_type.startswith(SSE):
            return _first_sse_json_message(response.text)
        if not response.text:
            return None
        raise McpProtocolError(f"Unexpected response content-type: {content_type!r}")

    def _request_id(self) -> int:
        request_id = self._next_id
        self._next_id += 1
        return request_id


def _first_sse_json_message(text: str) -> dict[str, Any] | None:
    for event in _iter_sse_events(text):
        if event.get("event", "message") != "message":
            continue
        data = event.get("data")
        if not data:
            continue
        value = json.loads(data)
        if isinstance(value, dict):
            return value
        raise McpProtocolError("SSE message data is not a JSON object")
    return None


def _is_tool_error(message: dict[str, Any]) -> bool:
    result = message.get("result")
    return isinstance(result, dict) and result.get("isError") is True


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


def _iter_sse_events(text: str) -> Iterator[dict[str, str]]:
    event: dict[str, list[str]] = {}
    for raw_line in text.splitlines():
        line = raw_line.rstrip("\r")
        if not line:
            if event:
                yield _join_sse_event(event)
                event = {}
            continue
        if line.startswith(":"):
            continue
        field, _, value = line.partition(":")
        if value.startswith(" "):
            value = value[1:]
        event.setdefault(field, []).append(value)
    if event:
        yield _join_sse_event(event)


def _join_sse_event(event: dict[str, list[str]]) -> dict[str, str]:
    return {key: "\n".join(values) for key, values in event.items()}
