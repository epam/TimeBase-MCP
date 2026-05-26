from timebase_mcp.clients.factory import get_detected_edition
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from timebase_mcp.config import MCPSettings
from timebase_mcp.models import MCPServerConfiguration


def register_system_tools(mcp: FastMCP, settings: MCPSettings) -> None:

    @mcp.tool(
        name="get_server_configuration",
        description="Get the MCP server runtime configuration, including detected TimeBase server edition and connection parameters. "
        "Edition being None indicates that it has not been inferred from configuration or no successful connection to TimeBase has been made yet.",
        annotations=ToolAnnotations(
            title="Get MCP server configuration",
            readOnlyHint=True,
            openWorldHint=False,
        ),
    )
    def get_server_configuration() -> MCPServerConfiguration:
        return MCPServerConfiguration(
            transport=settings.transport,
            tb_url=settings.tb_url,
            tb_username=settings.tb_username,
            edition=get_detected_edition(settings),
        )

    _ = get_server_configuration
