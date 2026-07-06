from __future__ import annotations

import sys
from collections.abc import Sequence

from timebase_mcp.cli.parser import (
    build_parser,
    normalize_argv,
    run_keys_command,
)
from timebase_mcp.cli.server import run_server
from timebase_mcp.cli.servers import servers_print
from timebase_mcp.version import get_version


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    effective_argv = normalize_argv(sys.argv[1:] if argv is None else argv)
    args = parser.parse_args(effective_argv)

    if args.version:
        print(f"timebase-mcp {get_version()}")
        return 0

    if args.command == "keys":
        return run_keys_command(parser, args)

    if args.command == "servers-print":
        return servers_print(args)

    return run_server()
