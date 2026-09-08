from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ToolAnnotations
from pydantic import Field

from timebase_mcp.errors import TimeBaseMCPError
from timebase_mcp.models.logs_kb import SearchLogsKBResult
from timebase_mcp.runtime.state import TimeBaseRuntime
from timebase_mcp.services.logs_kb.search import (
    search_logs_kb as search_logs_kb_service,
)


def register_logs_kb_tools(mcp: MCPServer) -> None:

    @mcp.tool(
        name="search_logs_kb",
        description=(
            "Search the TimeBase logs knowledge base using a log excerpt, stack trace, "
            "or error text, and return the most relevant troubleshooting matches."
        ),
        annotations=ToolAnnotations(
            title="Search TimeBase logs knowledge base",
            read_only_hint=True,
            open_world_hint=False,
        ),
    )
    async def search_logs_kb(
        ctx: Context[TimeBaseRuntime],
        query: str = Field(
            description="Raw log text, stack trace, or error excerpt to search for."
        ),
        limit: int = Field(
            default=5,
            ge=1,
            description="Maximum number of matches to return.",
        ),
    ) -> SearchLogsKBResult:
        _ = ctx
        try:
            return search_logs_kb_service(query=query, limit=limit)
        except (TimeBaseMCPError, ValueError) as exc:
            raise ToolError(str(exc)) from exc

    _ = search_logs_kb
