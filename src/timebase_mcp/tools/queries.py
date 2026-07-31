from typing import Literal

from mcp.server.mcpserver import Context, MCPServer
from mcp_types import ToolAnnotations
from pydantic import Field

from timebase_mcp.models.core import CompileQQLResult, QQLFunctionsResult
from timebase_mcp.runtime.operations import run_with_context
from timebase_mcp.services import queries as query_service
from timebase_mcp.runtime.state import TimeBaseRuntime
from timebase_mcp.tools.common import InstanceName


def register_query_tools(mcp: MCPServer) -> None:

    @mcp.tool(
        name="execute_query",
        description="Execute a TimeBase QQL query",
        annotations=ToolAnnotations(
            title="Execute TimeBase QQL query",
            read_only_hint=False,
            destructive_hint=True,
            idempotent_hint=False,
            open_world_hint=True,
        ),
    )
    async def execute_query(
        ctx: Context[TimeBaseRuntime],
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
            lambda client: query_service.execute_query(client, query, limit),
            instance_key=instance_key,
            report_progress=True,
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
            read_only_hint=True,
            open_world_hint=True,
        ),
    )
    async def compile_query(
        ctx: Context[TimeBaseRuntime],
        instance_key: InstanceName = None,
        query: str = Field(description="TimeBase QQL query text"),
    ) -> CompileQQLResult:
        return await run_with_context(
            ctx,
            lambda client: query_service.compile_query(client, query),
            instance_key=instance_key,
        )

    @mcp.tool(
        name="list_qql_functions",
        description=(
            "List QQL function signatures supported by the connected TimeBase server"
        ),
        annotations=ToolAnnotations(
            title="List available TimeBase QQL function signatures",
            read_only_hint=True,
            open_world_hint=True,
        ),
    )
    async def list_qql_functions(
        ctx: Context[TimeBaseRuntime],
        instance_key: InstanceName = None,
        kind: Literal["all", "stateless", "stateful"] = Field(
            default="all",
            description="Function category to return",
        ),
        function_id: str | None = Field(
            default=None,
            description=(
                "Optional exact QQL function id to return, e.g. ABS or SMA. "
                "When provided, TimeBase filters overloads server-side."
            ),
        ),
    ) -> QQLFunctionsResult:
        return await run_with_context(
            ctx,
            lambda client: query_service.list_qql_functions(client, kind, function_id),
            instance_key=instance_key,
            report_progress=True,
        )

    _ = (execute_query, compile_query, list_qql_functions)
