from urllib.parse import unquote

from mcp.server.fastmcp import FastMCP

from timebase_mcp.operations import run_with_context


def register_resources(mcp: FastMCP) -> None:
    """Register stable TimeBase metadata resources."""

    async def _run_resource_operation(operation, *, instance_key: str | None = None):
        return await run_with_context(
            mcp.get_context(), operation, instance_key=instance_key
        )

    @mcp.resource(
        "timebase://streams",
        name="stream_catalog",
        title="TimeBase Stream Catalog",
        description="Resource listing streams and descriptions.",
        mime_type="text/plain",
    )
    async def stream_catalog_resource() -> str:
        streams = await _run_resource_operation(lambda client: client.list_streams())
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
    async def stream_schema_resource(stream_key: str) -> str:
        schema = await _run_resource_operation(
            lambda client: client.get_stream_schema(stream_key),
        )
        return schema.schema_text

    @mcp.resource(
        "timebase://instances/{instance_key}/streams",
        name="instance_stream_catalog",
        title="TimeBase Instance Stream Catalog",
        description="Resource listing streams and descriptions for one instance.",
        mime_type="text/plain",
    )
    async def instance_stream_catalog_resource(instance_key: str) -> str:
        instance_key = unquote(instance_key)
        streams = await _run_resource_operation(
            lambda client: client.list_streams(),
            instance_key=instance_key,
        )
        if not streams:
            return "No streams found."
        return "\n".join(
            f"{stream.key}: {stream.description or 'No description'}"
            for stream in streams
        )

    @mcp.resource(
        "timebase://instances/{instance_key}/streams/{stream_key}/schema",
        name="instance_stream_schema",
        title="TimeBase Instance Stream Schema",
        description="Resource exposing a stream schema by instance and stream key.",
        mime_type="text/plain",
    )
    async def instance_stream_schema_resource(
        instance_key: str, stream_key: str
    ) -> str:
        instance_key = unquote(instance_key)
        schema = await _run_resource_operation(
            lambda client: client.get_stream_schema(stream_key),
            instance_key=instance_key,
        )
        return schema.schema_text

    _ = (
        stream_catalog_resource,
        stream_schema_resource,
        instance_stream_catalog_resource,
        instance_stream_schema_resource,
    )
