from mcp.server.fastmcp import Context, FastMCP
from mcp.server.session import ServerSession
from mcp.types import ToolAnnotations
from pydantic import Field

from timebase_mcp.models import (
    StreamInfo,
    StreamSchema,
    StreamSpaces,
    StreamSpaceTimeRange,
    StreamSymbols,
    StreamTimeRange,
)
from timebase_mcp.operations import run_with_context
from timebase_mcp.runtime import TimeBaseRuntime
from timebase_mcp.tools.common import InstanceName


def register_stream_tools(mcp: FastMCP) -> None:

    @mcp.tool(
        name="list_streams",
        description="List available TimeBase streams with their descriptions",
        annotations=ToolAnnotations(
            title="List TimeBase streams",
            readOnlyHint=True,
            openWorldHint=True,
        ),
    )
    async def list_streams(
        ctx: Context[ServerSession, TimeBaseRuntime],
        instance_key: InstanceName = None,
    ) -> list[StreamInfo]:
        return await run_with_context(
            ctx,
            lambda client: client.list_streams(),
            instance_key=instance_key,
        )

    @mcp.tool(
        name="get_stream_schema",
        description="Get the schema of a specific stream",
        annotations=ToolAnnotations(
            title="Get TimeBase stream schema",
            readOnlyHint=True,
            openWorldHint=True,
        ),
    )
    async def get_stream_schema(
        ctx: Context[ServerSession, TimeBaseRuntime],
        stream_key: str = Field(description="Stream key to inspect"),
        instance_key: InstanceName = None,
    ) -> StreamSchema:
        return await run_with_context(
            ctx,
            lambda client: client.get_stream_schema(stream_key),
            instance_key=instance_key,
        )

    @mcp.tool(
        name="get_stream_time_range",
        description="Get the time range of a specific stream in UTC",
        annotations=ToolAnnotations(
            title="Get TimeBase stream time range in UTC",
            readOnlyHint=True,
            openWorldHint=True,
        ),
    )
    async def get_stream_time_range(
        ctx: Context[ServerSession, TimeBaseRuntime],
        stream_key: str = Field(description="Stream key to inspect"),
        instance_key: InstanceName = None,
    ) -> StreamTimeRange:
        return await run_with_context(
            ctx,
            lambda client: client.get_stream_time_range(stream_key),
            instance_key=instance_key,
        )

    @mcp.tool(
        name="list_stream_spaces",
        description="List spaces for a specific TimeBase stream",
        annotations=ToolAnnotations(
            title="List TimeBase stream spaces",
            readOnlyHint=True,
            openWorldHint=True,
        ),
    )
    async def list_stream_spaces(
        ctx: Context[ServerSession, TimeBaseRuntime],
        stream_key: str = Field(description="Stream key to inspect"),
        instance_key: InstanceName = None,
    ) -> StreamSpaces:
        return await run_with_context(
            ctx,
            lambda client: client.get_stream_spaces(stream_key),
            instance_key=instance_key,
        )

    @mcp.tool(
        name="get_stream_space_time_range",
        description="Get the time range of a specific stream space in UTC",
        annotations=ToolAnnotations(
            title="Get TimeBase stream space time range in UTC",
            readOnlyHint=True,
            openWorldHint=True,
        ),
    )
    async def get_stream_space_time_range(
        ctx: Context[ServerSession, TimeBaseRuntime],
        stream_key: str = Field(description="Stream key to inspect"),
        space: str = Field(
            description="Stream space to inspect; use an empty string for the default space",
        ),
        instance_key: InstanceName = None,
    ) -> StreamSpaceTimeRange:
        return await run_with_context(
            ctx,
            lambda client: client.get_stream_space_time_range(stream_key, space),
            instance_key=instance_key,
        )

    @mcp.tool(
        name="get_stream_symbols",
        description="Get the symbols of a specific stream",
        annotations=ToolAnnotations(
            title="Get TimeBase stream symbols",
            readOnlyHint=True,
            openWorldHint=True,
        ),
    )
    async def get_stream_symbols(
        ctx: Context[ServerSession, TimeBaseRuntime],
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
            lambda client: client.get_stream_symbols(
                stream_key=stream_key,
                limit=limit,
                cursor=cursor,
            ),
            instance_key=instance_key,
        )

    @mcp.tool(
        name="get_stream_messages",
        description="Get the first or last N messages from a stream",
        annotations=ToolAnnotations(
            title="Get stream messages",
            readOnlyHint=True,
            openWorldHint=True,
        ),
    )
    async def get_stream_messages(
        ctx: Context[ServerSession, TimeBaseRuntime],
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
            lambda client: client.get_stream_messages_text(
                stream_key,
                reverse,
                count,
                space,
            ),
            instance_key=instance_key,
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
