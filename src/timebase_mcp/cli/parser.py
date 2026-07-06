from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from timebase_mcp.cli.keys import keys_generate, keys_list, keys_revoke


def is_cli_invocation() -> bool:
    return Path(sys.argv[0]).stem == "timebase-mcp"


def normalize_argv(argv: Sequence[str]) -> list[str]:
    return [arg for arg in argv if arg]


def build_parser() -> argparse.ArgumentParser:
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

    servers_print_parser = subparsers.add_parser(
        "servers-print",
        help="Print quoted TIMEBASE_SERVERS value for mcp.json env.",
    )
    servers_print_parser.add_argument(
        "file",
        type=Path,
        help="Path to a JSON file containing an array of server objects.",
    )

    return parser


def run_keys_command(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    handlers = {
        "generate": keys_generate,
        "list": keys_list,
        "revoke": keys_revoke,
    }
    handler = handlers.get(args.keys_command)
    if handler is None:
        parser.parse_args(["keys", "--help"])
        return 2
    return handler(args)
