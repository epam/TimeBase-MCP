from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import sys
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from importlib import metadata
from pathlib import Path
from types import FrameType

from mcp.server.fastmcp import FastMCP
from pydantic import ValidationError

from timebase_mcp.auth import keystore
from timebase_mcp.config import MCPSettings, ServerConfig, load_servers_from_path
from timebase_mcp.errors import ConfigurationError
from timebase_mcp.logging_config import configure_logging
from timebase_mcp.server import create_server

logger = logging.getLogger("timebase_mcp")

_DIST_NAME = "timebase-mcp"
_STDIO_STARTUP_MESSAGE = (
    "TimeBase MCP server is running over stdio and waiting for an MCP client. "
)

server: FastMCP | None = None


def get_version() -> str:
    try:
        return metadata.version(_DIST_NAME)
    except metadata.PackageNotFoundError:
        return "unknown"


def _is_cli_invocation() -> bool:
    return Path(sys.argv[0]).stem == "timebase-mcp"


def _should_log_terminal_status() -> bool:
    return sys.stderr.isatty()


def _normalize_argv(argv: Sequence[str]) -> list[str]:
    return [arg for arg in argv if arg]


def load_settings() -> MCPSettings:
    try:
        return MCPSettings()
    except ValidationError as exc:
        raw_settings = "<unavailable>"
        try:
            raw_settings = json.dumps(
                MCPSettings.debug_log_payload_from_env(), sort_keys=True
            )
        except Exception:
            pass

        logger.error(
            "Invalid TimeBase MCP configuration: %s. Raw settings: %s",
            exc,
            raw_settings,
        )
        raise ConfigurationError("Invalid TimeBase MCP configuration.") from exc


def build_server(settings: MCPSettings | None = None) -> FastMCP:
    effective_settings = settings or load_settings()
    return create_server(effective_settings)


def warn_remote_operational_defaults(settings: MCPSettings) -> None:
    if settings.is_remote_http_bind and settings.max_concurrent_ops == 0:
        logger.warning(
            "MCP_MAX_CONCURRENT_OPS=0 disables admission control for a "
            "non-loopback HTTP deployment. Set MCP_MAX_CONCURRENT_OPS to a "
            "positive value for shared remote servers."
        )


def _raise_keyboard_interrupt(_signum: int, _frame: FrameType | None) -> None:
    raise KeyboardInterrupt()


@contextmanager
def immediate_sigint_handler() -> Iterator[None]:
    try:
        previous_handler = signal.getsignal(signal.SIGINT)
        signal.signal(signal.SIGINT, _raise_keyboard_interrupt)
    except ValueError:
        yield
        return

    try:
        yield
    finally:
        signal.signal(signal.SIGINT, previous_handler)


def run_server() -> int:
    try:
        active_settings = load_settings()
        configure_logging(active_settings)
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "TimeBase MCP configuration: %s",
                json.dumps(active_settings.debug_log_payload(), sort_keys=True),
            )
        warn_remote_operational_defaults(active_settings)
        active_server = build_server(active_settings)
    except ConfigurationError:
        return 1
    except Exception as exc:
        logger.error("Failed to start TimeBase MCP server: %s", exc)
        return 1

    try:
        with immediate_sigint_handler():
            if active_settings.transport == "stdio" and _should_log_terminal_status():
                logger.info(_STDIO_STARTUP_MESSAGE)

            active_server.run(transport=active_settings.transport)
    except KeyboardInterrupt:
        if active_settings.transport == "stdio" and _should_log_terminal_status():
            logger.info("TimeBase MCP server stopped.")
        return 130
    except Exception as exc:
        logger.error("TimeBase MCP server failed: %s", exc)
        return 1

    return 0


if __name__ != "__main__" and not _is_cli_invocation():
    server = build_server()


def _parse_scopes(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [scope for scope in raw.replace(",", " ").split() if scope]


def _resolve_store_path(file_arg: str | None) -> Path | None:
    path = file_arg or os.environ.get("MCP_AUTH_API_KEYS_FILE")
    return Path(path) if path else None


def _keys_generate(args: argparse.Namespace) -> int:
    scopes = _parse_scopes(args.scopes)
    path = _resolve_store_path(args.file)

    if args.stdout or path is None:
        record, raw_key = keystore.build_record(name=args.name, scopes=scopes)
        print(json.dumps(record.to_json(), indent=2))
        print(f"\nAPI key (shown once, store securely): {raw_key}", file=sys.stderr)
        if path is None and not args.stdout:
            print(
                "No key store path given (--file or MCP_AUTH_API_KEYS_FILE); the "
                "record above was not persisted.",
                file=sys.stderr,
            )
        return 0

    try:
        record, raw_key = keystore.add_key(path=path, name=args.name, scopes=scopes)
    except ValueError as exc:
        print(f"Failed to update key store {path}: {exc}", file=sys.stderr)
        return 1
    print(f"Added API key '{record.name}' (id {record.id}) to {path}.")
    print(f"API key (shown once, store securely): {raw_key}")
    return 0


def _keys_list(args: argparse.Namespace) -> int:
    path = _resolve_store_path(args.file)
    if path is None:
        print(
            "No key store specified. Use --file or set MCP_AUTH_API_KEYS_FILE.",
            file=sys.stderr,
        )
        return 2
    try:
        records = keystore.load_store(path) if path.exists() else ()
    except ValueError as exc:
        print(f"Invalid key store {path}: {exc}", file=sys.stderr)
        return 1
    if not records:
        print("No API keys.")
        return 0
    print(f"{'ID':<10} {'NAME':<24} {'SCOPES':<24} CREATED")
    for record in records:
        scopes = ",".join(record.scopes) or "-"
        print(
            f"{record.id:<10} {record.name:<24} {scopes:<24} {record.created_at or '-'}"
        )
    return 0


def _keys_revoke(args: argparse.Namespace) -> int:
    path = _resolve_store_path(args.file)
    if path is None:
        print(
            "No key store specified. Use --file or set MCP_AUTH_API_KEYS_FILE.",
            file=sys.stderr,
        )
        return 2
    if not path.exists():
        print(f"Key store {path} does not exist.", file=sys.stderr)
        return 1
    try:
        removed = keystore.remove_keys(path=path, identifier=args.identifier)
    except ValueError as exc:
        print(f"Invalid key store {path}: {exc}", file=sys.stderr)
        return 1
    if not removed:
        print(f"No API key matching '{args.identifier}'.", file=sys.stderr)
        return 1
    for record in removed:
        print(f"Revoked API key '{record.name}' (id {record.id}).")
    return 0


def _servers_print(args: argparse.Namespace) -> int:
    try:
        raw_servers = load_servers_from_path(args.file)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 1

    try:
        servers = [ServerConfig.model_validate(entry) for entry in raw_servers]
    except ValidationError as exc:
        print(exc, file=sys.stderr)
        return 1

    if not servers:
        print("Servers file must contain at least one server.", file=sys.stderr)
        return 1

    payload = [server.model_dump(mode="json", exclude_none=True) for server in servers]
    compact = json.dumps(payload, separators=(",", ":"))
    print(json.dumps(compact))
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="timebase-mcp")
    parser.add_argument(
        "-v",
        "--version",
        action="store_true",
        help="Print the installed timebase-mcp version and exit.",
    )
    subparsers = parser.add_subparsers(dest="command")

    keys_parser = subparsers.add_parser(
        "keys", help="Generate and manage inbound API keys."
    )
    keys_sub = keys_parser.add_subparsers(dest="keys_command")

    generate = keys_sub.add_parser("generate", help="Generate a new API key.")
    generate.add_argument("--name", required=True, help="Name for the key.")
    generate.add_argument(
        "--scopes", default=None, help="Comma/space-separated scopes for the key."
    )
    generate.add_argument(
        "--file",
        default=None,
        help="Key store path (defaults to MCP_AUTH_API_KEYS_FILE).",
    )
    generate.add_argument(
        "--stdout",
        action="store_true",
        help="Print the hashed record to stdout instead of writing the store.",
    )

    list_keys = keys_sub.add_parser("list", help="List API keys in the store.")
    list_keys.add_argument(
        "--file",
        default=None,
        help="Key store path (defaults to MCP_AUTH_API_KEYS_FILE).",
    )

    revoke = keys_sub.add_parser("revoke", help="Remove an API key by id or name.")
    revoke.add_argument("identifier", help="Key id or name to remove.")
    revoke.add_argument(
        "--file",
        default=None,
        help="Key store path (defaults to MCP_AUTH_API_KEYS_FILE).",
    )

    servers_print = subparsers.add_parser(
        "servers-print",
        help="Print quoted TIMEBASE_SERVERS value for mcp.json env.",
    )
    servers_print.add_argument(
        "file",
        type=Path,
        help="Path to a JSON file containing an array of server objects.",
    )

    return parser


def _run_keys_command(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    handlers = {
        "generate": _keys_generate,
        "list": _keys_list,
        "revoke": _keys_revoke,
    }
    handler = handlers.get(args.keys_command)
    if handler is None:
        parser.parse_args(["keys", "--help"])
        return 2
    return handler(args)


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    effective_argv = _normalize_argv(sys.argv[1:] if argv is None else argv)
    args = parser.parse_args(effective_argv)

    if args.version:
        print(f"timebase-mcp {get_version()}")
        return 0

    if args.command == "keys":
        return _run_keys_command(parser, args)

    if args.command == "servers-print":
        return _servers_print(args)

    return run_server()


if __name__ == "__main__":
    raise SystemExit(main())
