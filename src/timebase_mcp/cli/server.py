from __future__ import annotations

import json
import logging
import signal
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from types import FrameType

from mcp.server.fastmcp import FastMCP
from pydantic import ValidationError

from timebase_mcp.cli.logging import configure_logging
from timebase_mcp.config.settings import MCPSettings
from timebase_mcp.errors import ConfigurationError
from timebase_mcp.server import create_server

logger = logging.getLogger("timebase_mcp")

_STDIO_STARTUP_MESSAGE = (
    "TimeBase MCP server is running over stdio and waiting for an MCP client. "
)


def should_log_terminal_status() -> bool:
    return sys.stderr.isatty()


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
            if active_settings.transport == "stdio" and should_log_terminal_status():
                logger.info(_STDIO_STARTUP_MESSAGE)

            active_server.run(transport=active_settings.transport)
    except KeyboardInterrupt:
        if active_settings.transport == "stdio" and should_log_terminal_status():
            logger.info("TimeBase MCP server stopped.")
        return 130
    except Exception as exc:
        logger.error("TimeBase MCP server failed: %s", exc)
        return 1

    return 0
