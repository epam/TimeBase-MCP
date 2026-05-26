import logging
from collections.abc import Callable
from typing import TypeVar

from timebase_mcp.clients.base import TimeBaseClient
from timebase_mcp.clients.factory import create_timebase_client
from timebase_mcp.config import MCPSettings

ResultT = TypeVar("ResultT")
logger = logging.getLogger(__name__)


def run_with_client(
    settings: MCPSettings,
    operation: Callable[[TimeBaseClient], ResultT],
    *,
    read_only: bool = True,
) -> ResultT:
    """Run a TimeBase operation and surface expected errors as MCP-friendly values."""
    try:
        client = create_timebase_client(settings, read_only=read_only)
        try:
            return operation(client)
        finally:
            client.close()
    except Exception as exc:
        logger.error("Error during TimeBase operation: %s", exc, exc_info=True)
        raise ValueError(str(exc)) from exc
