from mcp.server.fastmcp import FastMCP

from timebase_mcp.config import MCPSettings
from timebase_mcp.constants import APP_NAME
from timebase_mcp.instructions import SERVER_INSTRUCTIONS
from timebase_mcp.resources import register_resources
from timebase_mcp.tools import register_tools


def create_server(settings: MCPSettings) -> FastMCP:
    mcp = FastMCP(
        name=APP_NAME,
        instructions=SERVER_INSTRUCTIONS,
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level,
    )
    register_tools(mcp, settings)
    register_resources(mcp, settings)
    return mcp
