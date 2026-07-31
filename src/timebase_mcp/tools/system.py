from typing import Literal

from mcp.server.mcpserver import Context, MCPServer
from mcp_types import ToolAnnotations
from pydantic import Field

from timebase_mcp.models.core import MCPServerConfiguration, TimeBaseInstanceInfo
from timebase_mcp.models.monitoring import (
    TimeBaseActivityDetail,
    TimeBaseActivityList,
    TimeBaseStatus,
)
from timebase_mcp.runtime.introspection import build_server_configuration
from timebase_mcp.runtime.state import TimeBaseRuntime
from timebase_mcp.services.monitoring import (
    get_timebase_activity_detail as get_activity_detail,
)
from timebase_mcp.services.monitoring import (
    get_timebase_status as get_status,
)
from timebase_mcp.services.monitoring import (
    list_timebase_activity as list_activity,
)
from timebase_mcp.tools.common import InstanceName

_LIMITED_SERVER_SUPPORT_NOTE = "Limited TimeBase server versions support."


def register_system_tools(mcp: MCPServer) -> None:

    @mcp.tool(
        name="list_timebase_instances",
        description="List configured TimeBase server instances.",
        annotations=ToolAnnotations(
            title="List TimeBase instances",
            read_only_hint=True,
            open_world_hint=False,
        ),
    )
    async def list_timebase_instances(
        ctx: Context[TimeBaseRuntime],
    ) -> list[TimeBaseInstanceInfo]:
        runtime = ctx.request_context.lifespan_context
        return [
            TimeBaseInstanceInfo(
                name=instance.key,
                description=instance.config.description,
                read_only=instance.config.read_only,
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
            read_only_hint=True,
            open_world_hint=False,
        ),
    )
    async def get_server_configuration(
        ctx: Context[TimeBaseRuntime],
    ) -> MCPServerConfiguration:
        runtime = ctx.request_context.lifespan_context
        return build_server_configuration(runtime)

    @mcp.tool(
        name="get_timebase_status",
        description=(
            f"Get TimeBase version, license, and runtime environment. "
            f"{_LIMITED_SERVER_SUPPORT_NOTE}"
        ),
        annotations=ToolAnnotations(
            title="Get TimeBase status",
            read_only_hint=True,
            open_world_hint=True,
        ),
    )
    async def get_timebase_status(
        ctx: Context[TimeBaseRuntime],
        instance_key: InstanceName = None,
    ) -> TimeBaseStatus:
        runtime = ctx.request_context.lifespan_context
        return await get_status(runtime, instance_key=instance_key)

    @mcp.tool(
        name="list_timebase_activity",
        description=(
            f"List active cursors, loaders, connections, and locks. "
            f"{_LIMITED_SERVER_SUPPORT_NOTE}"
        ),
        annotations=ToolAnnotations(
            title="List TimeBase activity",
            read_only_hint=True,
            open_world_hint=True,
        ),
    )
    async def list_timebase_activity(
        ctx: Context[TimeBaseRuntime],
        instance_key: InstanceName = None,
        kind: Literal["all", "cursors", "loaders", "connections", "locks"] = Field(
            default="all",
            description="Activity collection to return.",
        ),
        limit: int = Field(
            default=50,
            ge=1,
            le=500,
            description="Maximum number of rows to return for each requested collection.",
        ),
    ) -> TimeBaseActivityList:
        runtime = ctx.request_context.lifespan_context
        return await list_activity(
            runtime,
            instance_key=instance_key,
            kind=kind,
            limit=limit,
        )

    @mcp.tool(
        name="get_timebase_activity_detail",
        description=(
            f"Get details for one cursor, loader, connection, or lock. "
            f"{_LIMITED_SERVER_SUPPORT_NOTE}"
        ),
        annotations=ToolAnnotations(
            title="Get TimeBase activity detail",
            read_only_hint=True,
            open_world_hint=True,
        ),
    )
    async def get_timebase_activity_detail(
        ctx: Context[TimeBaseRuntime],
        kind: Literal["cursor", "loader", "connection", "lock"] = Field(
            description="Activity object kind to inspect.",
        ),
        id: str = Field(
            description="Cursor/loader numeric id, connection client id, or lock id/guid/client id.",
        ),
        instance_key: InstanceName = None,
        include_instruments: bool = Field(
            default=False,
            description="For cursor/loader details, include an instrument page.",
        ),
        instrument_offset: int = Field(
            default=0,
            ge=0,
            description="Instrument page offset when include_instruments is true.",
        ),
        instrument_limit: int = Field(
            default=50,
            ge=1,
            le=500,
            description="Instrument page size when include_instruments is true.",
        ),
        instrument_filter: str | None = Field(
            default=None,
            description="Optional instrument filter when include_instruments is true.",
        ),
    ) -> TimeBaseActivityDetail:
        runtime = ctx.request_context.lifespan_context
        return await get_activity_detail(
            runtime,
            instance_key=instance_key,
            kind=kind,
            id=id,
            include_instruments=include_instruments,
            instrument_offset=instrument_offset,
            instrument_limit=instrument_limit,
            instrument_filter=instrument_filter,
        )

    _ = (
        list_timebase_instances,
        get_server_configuration,
        get_timebase_status,
        list_timebase_activity,
        get_timebase_activity_detail,
    )
