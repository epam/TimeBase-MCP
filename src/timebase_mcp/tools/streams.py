from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from timebase_mcp.config import MCPSettings
from timebase_mcp.models import StreamInfo, StreamSchema, StreamSymbols, StreamTimeRange
from timebase_mcp.operations import run_with_client


def register_stream_tools(mcp: FastMCP, settings: MCPSettings) -> None:

    @mcp.tool(
        name="list_streams",
        description="List available TimeBase streams with their descriptions",
        annotations=ToolAnnotations(
            title="List TimeBase streams",
            readOnlyHint=True,
            openWorldHint=True,
        ),
    )
    def list_streams() -> list[StreamInfo]:
        return run_with_client(settings, lambda client: client.list_streams())

    @mcp.tool(
        name="get_stream_schema",
        description="Get the schema of a specific stream",
        annotations=ToolAnnotations(
            title="Get TimeBase stream schema",
            readOnlyHint=True,
            openWorldHint=True,
        ),
    )
    def get_stream_schema(
        stream_key: str = Field(description="Stream key to inspect"),
    ) -> StreamSchema:
        return run_with_client(
            settings,
            lambda client: client.get_stream_schema(stream_key),
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
    def get_stream_time_range(
        stream_key: str = Field(description="Stream key to inspect"),
    ) -> StreamTimeRange:
        return run_with_client(
            settings,
            lambda client: client.get_stream_time_range(stream_key),
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
    def get_stream_symbols(
        stream_key: str = Field(description="Stream key to inspect"),
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
        return run_with_client(
            settings,
            lambda client: client.get_stream_symbols(
                stream_key=stream_key,
                limit=limit,
                cursor=cursor,
            ),
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
    def get_stream_messages(
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
    ) -> str:
        return run_with_client(
            settings,
            lambda client: client.get_stream_messages_text(stream_key, reverse, count),
        )

    _ = (
        list_streams,
        get_stream_schema,
        get_stream_time_range,
        get_stream_symbols,
        get_stream_messages,
    )
