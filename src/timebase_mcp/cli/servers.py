from __future__ import annotations

import argparse
import json
import sys

from pydantic import ValidationError

from timebase_mcp.config.servers import ServerConfig, load_servers_from_path


def servers_print(args: argparse.Namespace) -> int:
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
