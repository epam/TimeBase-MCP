from mcp.server.fastmcp import Context, FastMCP
from mcp.server.session import ServerSession
from mcp.types import ToolAnnotations

from timebase_mcp.models import MCPServerConfiguration, TimeBaseInstanceInfo
from timebase_mcp.runtime import TimeBaseRuntime, build_server_configuration


def register_system_tools(mcp: FastMCP) -> None:

    @mcp.tool(
        name="list_timebase_instances",
        description="List configured TimeBase server instances.",
        annotations=ToolAnnotations(
            title="List TimeBase instances",
            readOnlyHint=True,
            openWorldHint=False,
        ),
    )
    async def list_timebase_instances(
        ctx: Context[ServerSession, TimeBaseRuntime],
    ) -> list[TimeBaseInstanceInfo]:
        runtime = ctx.request_context.lifespan_context
        return [
            TimeBaseInstanceInfo(
                name=instance.key,
                description=instance.config.description,
            )
            for instance in runtime.instances.values()
        ]

    @mcp.tool(
        name="get_server_configuration",
        description="Get the MCP server runtime configuration, "
        "some TB server configuration fields may be undefined or "
        "have default value until the first connection is established.",
        annotations=ToolAnnotations(
            title="Get MCP server configuration",
            readOnlyHint=True,
            openWorldHint=False,
        ),
    )
    async def get_server_configuration(
        ctx: Context[ServerSession, TimeBaseRuntime],
    ) -> MCPServerConfiguration:
        runtime = ctx.request_context.lifespan_context
        return build_server_configuration(runtime)

    _ = (list_timebase_instances, get_server_configuration)
