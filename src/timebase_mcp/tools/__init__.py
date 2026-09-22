from mcp.server.mcpserver import MCPServer

from timebase_mcp.runtime.state import TimeBaseRuntime
from timebase_mcp.tools.queries import register_query_tools
from timebase_mcp.tools.streams import register_stream_tools
from timebase_mcp.tools.system import register_system_tools
from timebase_mcp.tools.webadmin import register_webadmin_tools


def register_tools(mcp: MCPServer, runtime: TimeBaseRuntime) -> None:
    register_system_tools(mcp)
    register_stream_tools(mcp)
    register_query_tools(mcp)
    if any(
        instance.config.webadmin.url is not None
        for instance in runtime.instances.values()
    ):
        register_webadmin_tools(mcp)
