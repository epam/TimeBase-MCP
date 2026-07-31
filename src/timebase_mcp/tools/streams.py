from mcp.server.mcpserver import Context, MCPServer
from mcp_types import ToolAnnotations
from pydantic import Field

from timebase_mcp.models.core import (
    StreamInfo,
    StreamSchema,
    StreamSpaces,
    StreamSpaceTimeRange,
    StreamSymbols,
    StreamTimeRange,
)
from timebase_mcp.runtime.operations import run_with_context
from timebase_mcp.services import streams as stream_service
from timebase_mcp.runtime.state import TimeBaseRuntime
from timebase_mcp.tools.common import InstanceName


def register_stream_tools(mcp: MCPServer) -> None:

    @mcp.tool(
        name="list_streams",
        description="List available TimeBase streams with their descriptions",
        annotations=ToolAnnotations(
            title="List TimeBase streams",
            read_only_hint=True,
            open_world_hint=True,
        ),
    )
    async def list_streams(
        ctx: Context[TimeBaseRuntime],
        instance_key: InstanceName = None,
    ) -> list[StreamInfo]:
        return await run_with_context(
            ctx,
            lambda client: stream_service.list_streams(client),
            instance_key=instance_key,
        )

    @mcp.tool(
        name="get_stream_schema",
        description="Get the schema of a specific stream",
        annotations=ToolAnnotations(
            title="Get TimeBase stream schema",
            read_only_hint=True,
            open_world_hint=True,
        ),
    )
    async def get_stream_schema(
        ctx: Context[TimeBaseRuntime],
        stream_key: str = Field(description="Stream key to inspect"),
        instance_key: InstanceName = None,
    ) -> StreamSchema:
        return await run_with_context(
            ctx,
            lambda client: stream_service.get_stream_schema(client, stream_key),
            instance_key=instance_key,
        )

    @mcp.tool(
        name="get_stream_time_range",
        description="Get the time range of a specific stream in UTC",
        annotations=ToolAnnotations(
            title="Get TimeBase stream time range in UTC",
            read_only_hint=True,
            open_world_hint=True,
        ),
    )
    async def get_stream_time_range(
        ctx: Context[TimeBaseRuntime],
        stream_key: str = Field(description="Stream key to inspect"),
        instance_key: InstanceName = None,
    ) -> StreamTimeRange:
        return await run_with_context(
            ctx,
            lambda client: stream_service.get_stream_time_range(client, stream_key),
            instance_key=instance_key,
        )

    @mcp.tool(
        name="list_stream_spaces",
        description="List spaces for a specific TimeBase stream",
        annotations=ToolAnnotations(
            title="List TimeBase stream spaces",
            read_only_hint=True,
            open_world_hint=True,
        ),
    )
    async def list_stream_spaces(
        ctx: Context[TimeBaseRuntime],
        stream_key: str = Field(description="Stream key to inspect"),
        instance_key: InstanceName = None,
    ) -> StreamSpaces:
        return await run_with_context(
            ctx,
            lambda client: stream_service.get_stream_spaces(client, stream_key),
            instance_key=instance_key,
        )

    @mcp.tool(
        name="get_stream_space_time_range",
        description="Get the time range of a specific stream space in UTC",
        annotations=ToolAnnotations(
            title="Get TimeBase stream space time range in UTC",
            read_only_hint=True,
            open_world_hint=True,
        ),
    )
    async def get_stream_space_time_range(
        ctx: Context[TimeBaseRuntime],
        stream_key: str = Field(description="Stream key to inspect"),
        space: str = Field(
            description="Stream space to inspect; use an empty string for the default space",
        ),
        instance_key: InstanceName = None,
    ) -> StreamSpaceTimeRange:
        return await run_with_context(
            ctx,
            lambda client: stream_service.get_stream_space_time_range(
                client, stream_key, space
            ),
            instance_key=instance_key,
        )

    @mcp.tool(
        name="get_stream_symbols",
        description="Get the symbols of a specific stream",
        annotations=ToolAnnotations(
            title="Get TimeBase stream symbols",
            read_only_hint=True,
            open_world_hint=True,
        ),
    )
    async def get_stream_symbols(
        ctx: Context[TimeBaseRuntime],
        stream_key: str = Field(description="Stream key to inspect"),
        instance_key: InstanceName = None,
        limit: int = Field(
            default=100,
            ge=1,
            le=500,
            description="Maximum number of symbols to return in this page",
        ),
        cursor: str | None = Field(
            default=None,
            description=(
                "Opaque cursor from a previous call's next_cursor; omit on first page"
            ),
        ),
    ) -> StreamSymbols:
        return await run_with_context(
            ctx,
            lambda client: stream_service.get_stream_symbols(
                client,
                stream_key=stream_key,
                limit=limit,
                cursor=cursor,
            ),
            instance_key=instance_key,
            report_progress=True,
        )

    @mcp.tool(
        name="get_stream_messages",
        description="Get the first or last N messages from a stream",
        annotations=ToolAnnotations(
            title="Get stream messages",
            read_only_hint=True,
            open_world_hint=True,
        ),
    )
    async def get_stream_messages(
        ctx: Context[TimeBaseRuntime],
        instance_key: InstanceName = None,
        stream_key: str = Field(description="Stream key to inspect"),
        reverse: bool = Field(
            default=False,
            description="If true, read from the end of the stream and return the last N messages",
        ),
        count: int = Field(
            default=10,
            ge=1,
            le=100,
            description="Number of messages to retrieve",
        ),
        space: str | None = Field(
            default=None,
            description="Optional stream space to read from; use an empty string for the default space",
        ),
    ) -> str:
        return await run_with_context(
            ctx,
            lambda client: stream_service.get_stream_messages_text(
                client,
                stream_key,
                reverse,
                count,
                space,
            ),
            instance_key=instance_key,
            report_progress=True,
        )

    _ = (
        list_streams,
        get_stream_schema,
        get_stream_time_range,
        list_stream_spaces,
        get_stream_space_time_range,
        get_stream_symbols,
        get_stream_messages,
    )
