from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Literal, TypedDict


class EnvVar(TypedDict, total=False):
    name: str
    description: str
    default: str
    placeholder: str
    format: Literal["string", "number", "filepath"]
    isRequired: bool
    isSecret: bool
    choices: list[str]


VERSION_PLACEHOLDER = "__VERSION__"

COMMON_ENV: list[EnvVar] = [
    {
        "name": "TIMEBASE_URL",
        "description": "TimeBase native connection URL.",
        "default": "dxtick://localhost:8011",
        "placeholder": "dxtick://localhost:8011",
    },
    {
        "name": "TIMEBASE_SERVERS",
        "description": "Multi-server config as a JSON array string or path to a JSON file.",
        "format": "string",
    },
    {
        "name": "TIMEBASE_USERNAME",
        "description": "Username for basic auth or oauth2_client_credentials.",
        "format": "string",
    },
    {
        "name": "TIMEBASE_PASSWORD",
        "description": "Password for basic auth.",
        "isSecret": True,
        "format": "string",
    },
    {
        "name": "TIMEBASE_OAUTH2_TOKEN_URL",
        "description": "OAuth2 token endpoint for service-account client credentials.",
        "format": "string",
    },
    {
        "name": "TIMEBASE_OAUTH2_CLIENT_ID",
        "description": "OAuth2 client ID for service-account or interactive login.",
        "format": "string",
    },
    {
        "name": "TIMEBASE_OAUTH2_CLIENT_SECRET",
        "description": "OAuth2 client secret for service-account auth.",
        "isSecret": True,
        "format": "string",
    },
    {
        "name": "TIMEBASE_OAUTH2_SCOPE",
        "description": "OAuth2 scope(s) for service-account or interactive login.",
        "format": "string",
    },
    {
        "name": "MCP_LOG_LEVEL",
        "description": "Log level: DEBUG, INFO, WARNING, ERROR, or CRITICAL.",
        "default": "INFO",
        "choices": ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
    },
]

LOCAL_ENV: list[EnvVar] = [
    {
        "name": "TIMEBASE_AUTH_MODE",
        "description": "Outbound auth: auto, none, basic, oauth2_client_credentials, interactive.",
        "default": "auto",
        "choices": [
            "auto",
            "none",
            "basic",
            "oauth2_client_credentials",
            "interactive",
        ],
    },
    {
        "name": "MCP_HOST",
        "description": "Loopback host for interactive OAuth redirect in stdio mode.",
        "default": "127.0.0.1",
    },
    {
        "name": "MCP_PORT",
        "description": "Loopback port for interactive OAuth redirect in stdio mode.",
        "default": "8000",
        "format": "number",
    },
]

REMOTE_ENV: list[EnvVar] = [
    {
        "name": "TIMEBASE_AUTH_MODE",
        "description": "Outbound auth: auto, none, basic, oauth2_client_credentials, forward_identity.",
        "default": "auto",
        "choices": [
            "auto",
            "none",
            "basic",
            "oauth2_client_credentials",
            "forward_identity",
        ],
    },
    {
        "name": "MCP_AUTH_PUBLIC_URL",
        "description": "Public HTTPS URL of this MCP endpoint (e.g. https://mcp.example.com/mcp).",
        "format": "string",
    },
    {
        "name": "MCP_AUTH_AUDIENCE",
        "description": "Expected JWT audience for inbound IdP auth.",
        "format": "string",
    },
    {
        "name": "MCP_AUTH_API_KEYS_FILE",
        "description": "Path to a hashed API-key store for inbound bearer-key auth.",
        "format": "filepath",
    },
]


def environment_variables_for_transport(transport_type: str) -> list[EnvVar]:
    if transport_type == "stdio":
        return COMMON_ENV + LOCAL_ENV
    if transport_type == "streamable-http":
        return COMMON_ENV + REMOTE_ENV
    msg = f"unsupported transport type: {transport_type!r}"
    raise ValueError(msg)


def apply_environment_variables(data: dict[str, Any]) -> None:
    for package in data.get("packages", []):
        transport = package.get("transport")
        if not isinstance(transport, dict):
            msg = "package is missing transport"
            raise ValueError(msg)
        transport_type = transport.get("type")
        if not isinstance(transport_type, str):
            msg = "package transport is missing type"
            raise ValueError(msg)
        package["environmentVariables"] = environment_variables_for_transport(
            transport_type
        )


def render_server_metadata(
    version: str,
    *,
    template_path: Path = Path("server.template.json"),
    output_path: Path = Path("server.json"),
) -> None:
    if VERSION_PLACEHOLDER in version:
        msg = f"version must not contain {VERSION_PLACEHOLDER!r}"
        raise ValueError(msg)

    rendered = template_path.read_text().replace(VERSION_PLACEHOLDER, version)
    if VERSION_PLACEHOLDER in rendered:
        msg = f"{VERSION_PLACEHOLDER!r} remains in rendered template"
        raise ValueError(msg)

    data: dict[str, Any] = json.loads(rendered)
    apply_environment_variables(data)
    output_path.write_text(json.dumps(data, indent=2) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render MCP Registry metadata.")
    parser.add_argument("version", help="Release version without leading v.")
    parser.add_argument(
        "--template",
        type=Path,
        default=Path("server.template.json"),
        help="Path to the server metadata template.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("server.json"),
        help="Path to write rendered metadata.",
    )
    args = parser.parse_args(argv)

    render_server_metadata(
        args.version,
        template_path=args.template,
        output_path=args.output,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
