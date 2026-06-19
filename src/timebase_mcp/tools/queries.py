from typing import Annotated

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.session import ServerSession
from mcp.types import ToolAnnotations
from pydantic import Field

from timebase_mcp.models import CompileQQLResult
from timebase_mcp.operations import run_with_context
from timebase_mcp.runtime import TimeBaseRuntime

InstanceName = Annotated[
    str | None,
    Field(description="TB instance key."),
]


def register_query_tools(mcp: FastMCP) -> None:

    @mcp.tool(
        name="execute_query",
        description="Execute a TimeBase QQL query",
        annotations=ToolAnnotations(
            title="Execute TimeBase QQL query",
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=False,
            openWorldHint=True,
        ),
    )
    async def execute_query(
        ctx: Context[ServerSession, TimeBaseRuntime],
        instance_key: InstanceName = None,
        query: str = Field(description="TimeBase QQL query text"),
        limit: int = Field(
            default=50,
            ge=1,
            le=100,
            description="Maximum number of result rows to include in preview text",
        ),
    ) -> str:
        return await run_with_context(
            ctx,
            lambda client: client.execute_query(query, limit),
            instance_key=instance_key,
        )

    @mcp.tool(
        name="compile_query",
        description=(
            "Compile TimeBase QQL query. "
            "Returns parser-level diagnostics only (not full semantic/logical validation). "
            "error_token is the first unexpected token, which may be after the actual root cause."
        ),
        annotations=ToolAnnotations(
            title="Compile TimeBase QQL query",
            readOnlyHint=True,
            openWorldHint=True,
        ),
    )
    async def compile_query(
        ctx: Context[ServerSession, TimeBaseRuntime],
        instance_key: InstanceName = None,
        query: str = Field(description="TimeBase QQL query text"),
    ) -> CompileQQLResult:
        return await run_with_context(
            ctx,
            lambda client: client.compile_query(query),
            instance_key=instance_key,
        )

    _ = (execute_query, compile_query)
