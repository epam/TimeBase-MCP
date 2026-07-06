from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from timebase_mcp.cli.app import main
from timebase_mcp.cli.parser import is_cli_invocation
from timebase_mcp.cli.server import build_server

server: FastMCP | None = None

if __name__ != "__main__" and not is_cli_invocation():
    server = build_server()


if __name__ == "__main__":
    raise SystemExit(main())
