from __future__ import annotations

import argparse
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from importlib import metadata
import json
import logging
from pathlib import Path
import signal
import sys
from types import FrameType

from mcp.server.fastmcp import FastMCP
from pydantic import ValidationError

from timebase_mcp.config import MCPSettings
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


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="timebase-mcp")
    parser.add_argument(
        "-v",
        "--version",
        action="store_true",
        help="Print the installed timebase-mcp version and exit.",
    )
    effective_argv = _normalize_argv(sys.argv[1:] if argv is None else argv)
    args = parser.parse_args(effective_argv)

    if args.version:
        print(f"timebase-mcp {get_version()}")
        return 0

    return run_server()


if __name__ == "__main__":
    raise SystemExit(main())
