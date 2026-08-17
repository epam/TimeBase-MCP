from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from typing import Any, Protocol

JSON = "application/json"
SSE = "text/event-stream"
PROTOCOL_VERSION = "2026-07-28"


class _ResponseLike(Protocol):
    @property
    def text(self) -> str: ...

    @property
    def headers(self) -> Mapping[str, str]: ...

    def json(self) -> Any: ...


def build_client_meta(
    *,
    client_name: str,
    client_version: str = "0.1.0",
    protocol_version: str = PROTOCOL_VERSION,
) -> dict[str, Any]:
    return {
        "io.modelcontextprotocol/protocolVersion": protocol_version,
        "io.modelcontextprotocol/clientInfo": {
            "name": client_name,
            "version": client_version,
        },
        "io.modelcontextprotocol/clientCapabilities": {},
    }


def build_modern_headers(
    *,
    method: str,
    mcp_name: str | None = None,
    protocol_version: str | None = PROTOCOL_VERSION,
    include_method_header: bool = True,
) -> dict[str, str]:
    headers = {
        "accept": f"{JSON}, {SSE}",
        "content-type": JSON,
    }
    if protocol_version is not None:
        headers["mcp-protocol-version"] = protocol_version
    if include_method_header:
        headers["mcp-method"] = method
    if mcp_name is not None:
        headers["mcp-name"] = mcp_name
    return headers


def parse_jsonrpc_response(response: _ResponseLike) -> dict[str, Any] | None:
    """Parse a modern Streamable HTTP response body.

    Returns ``None`` for an empty body. Raises ``ValueError`` for unexpected
    content types or non-object payloads.
    """
    content_type = response.headers.get("content-type", "").lower()
    if content_type.startswith(JSON):
        payload = response.json()
    elif content_type.startswith(SSE):
        payload = first_sse_json_message(response.text)
        if payload is None:
            return None
    elif not response.text:
        return None
    else:
        raise ValueError(f"Unexpected response content-type: {content_type!r}")

    if not isinstance(payload, dict):
        raise ValueError("MCP response payload is not a JSON object")
    return payload


def first_sse_json_message(text: str) -> dict[str, Any] | None:
    """Return the first SSE ``message`` event that looks like a JSON-RPC body.

    Prefers objects with ``result`` or ``error`` so progress/noise events are
    skipped when present.
    """
    fallback: dict[str, Any] | None = None
    for event in iter_sse_events(text):
        if event.get("event", "message") != "message":
            continue
        data = event.get("data")
        if not data:
            continue
        value = json.loads(data)
        if not isinstance(value, dict):
            raise ValueError("SSE message data is not a JSON object")
        if "result" in value or "error" in value:
            return value
        if fallback is None:
            fallback = value
    return fallback


def iter_sse_events(text: str) -> Iterator[dict[str, str]]:
    event: dict[str, list[str]] = {}
    for raw_line in text.splitlines():
        line = raw_line.rstrip("\r")
        if not line:
            if event:
                yield {key: "\n".join(values) for key, values in event.items()}
                event = {}
            continue
        if line.startswith(":"):
            continue
        field, _, value = line.partition(":")
        if value.startswith(" "):
            value = value[1:]
        event.setdefault(field, []).append(value)
    if event:
        yield {key: "\n".join(values) for key, values in event.items()}
