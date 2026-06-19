from mcp.server.fastmcp import FastMCP

from timebase_mcp.tools.queries import register_query_tools
from timebase_mcp.tools.streams import register_stream_tools
from timebase_mcp.tools.system import register_system_tools


def register_tools(mcp: FastMCP) -> None:
    register_system_tools(mcp)
    register_stream_tools(mcp)
    register_query_tools(mcp)
