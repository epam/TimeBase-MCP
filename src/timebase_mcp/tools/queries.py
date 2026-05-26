from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from timebase_mcp.config import MCPSettings
from timebase_mcp.models import CompileQQLResult
from timebase_mcp.operations import run_with_client


def register_query_tools(mcp: FastMCP, settings: MCPSettings) -> None:
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
    def execute_query(
        query: str = Field(description="TimeBase QQL query text"),
        limit: int = Field(
            default=50,
            ge=1,
            le=100,
            description="Maximum number of result rows to include in preview text",
        ),
    ) -> str:
        return run_with_client(
            settings,
            lambda client: client.execute_query(query, limit),
            read_only=False,
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
    def compile_query(
        query: str = Field(description="TimeBase QQL query text"),
    ) -> CompileQQLResult:
        return run_with_client(
            settings,
            lambda client: client.compile_query(query),
            read_only=True,
        )

    _ = (execute_query, compile_query)
