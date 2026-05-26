from mcp.server.fastmcp import FastMCP

from timebase_mcp.config import MCPSettings
from timebase_mcp.operations import run_with_client


def register_resources(mcp: FastMCP, settings: MCPSettings) -> None:
    """Register stable TimeBase metadata resources."""

    @mcp.resource(
        "timebase://streams",
        name="stream_catalog",
        title="TimeBase Stream Catalog",
        description="Resource listing streams and descriptions.",
        mime_type="text/plain",
    )
    def stream_catalog_resource() -> str:
        streams = run_with_client(settings, lambda client: client.list_streams())
        if not streams:
            return "No streams found."
        return "\n".join(
            f"{stream.key}: {stream.description or 'No description'}"
            for stream in streams
        )

    @mcp.resource(
        "timebase://streams/{stream_key}/schema",
        name="stream_schema",
        title="TimeBase Stream Schema",
        description="Resource exposing a stream schema by key.",
        mime_type="text/plain",
    )
    def stream_schema_resource(stream_key: str) -> str:
        schema = run_with_client(
            settings,
            lambda client: client.get_stream_schema(stream_key),
        )
        return schema.schema_text

    _ = (stream_catalog_resource, stream_schema_resource)
