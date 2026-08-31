from collections.abc import Awaitable, Callable
from typing import Annotated, TypeVar

from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from timebase_mcp.clients.base import TimeBaseClient
from timebase_mcp.errors import TimeBaseMCPError
from timebase_mcp.runtime.operations import run_with_context
from timebase_mcp.runtime.state import TimeBaseRuntime

ResultT = TypeVar("ResultT")

InstanceName = Annotated[
    str | None,
    Field(
        description=(
            "TB instance key. Required when multiple TimeBase instances are configured."
        )
    ),
]


async def with_tool_errors(awaitable: Awaitable[ResultT]) -> ResultT:
    """Map domain errors to SDK ``ToolError`` so the agent still sees the message."""
    try:
        return await awaitable
    except TimeBaseMCPError as exc:
        raise ToolError(str(exc)) from exc


async def run_tool_operation(
    ctx: Context[TimeBaseRuntime],
    operation: Callable[[TimeBaseClient], ResultT],
    *,
    instance_key: str | None = None,
    report_progress: bool = False,
) -> ResultT:
    return await with_tool_errors(
        run_with_context(
            ctx,
            operation,
            instance_key=instance_key,
            report_progress=report_progress,
        )
    )
