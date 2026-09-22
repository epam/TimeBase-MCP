from mcp.server.mcpserver import Context, MCPServer
from mcp_types import ToolAnnotations
from pydantic import Field

from timebase_mcp.models.webadmin import (
    OrderBookValidationIssues,
    WebAdminBackgroundTask,
    WebAdminInfo,
    WebAdminSchema,
    WebAdminTopics,
    WebAdminView,
    WebAdminViews,
)
from timebase_mcp.runtime.state import TimeBaseRuntime
from timebase_mcp.services import webadmin as webadmin_service
from timebase_mcp.tools.common import InstanceName, with_tool_errors


def register_webadmin_tools(mcp: MCPServer) -> None:
    @mcp.tool(
        name="get_webadmin_info",
        description="Get TimeBase WebAdmin version, connection, and authentication information.",
        annotations=ToolAnnotations(
            title="Get TimeBase WebAdmin info",
            read_only_hint=True,
            open_world_hint=True,
        ),
    )
    async def get_webadmin_info(
        ctx: Context[TimeBaseRuntime],
        instance_key: InstanceName = None,
    ) -> WebAdminInfo:
        runtime = ctx.request_context.lifespan_context
        return await with_tool_errors(
            webadmin_service.get_webadmin_info(runtime, instance_key=instance_key)
        )

    @mcp.tool(
        name="list_webadmin_views",
        description="List WebAdmin query views",
        annotations=ToolAnnotations(
            title="List WebAdmin views",
            read_only_hint=True,
            open_world_hint=True,
        ),
    )
    async def list_webadmin_views(
        ctx: Context[TimeBaseRuntime],
        instance_key: InstanceName = None,
    ) -> WebAdminViews:
        return await with_tool_errors(
            webadmin_service.list_webadmin_views(
                ctx.request_context.lifespan_context,
                instance_key=instance_key,
            )
        )

    @mcp.tool(
        name="get_webadmin_view",
        description="Get one WebAdmin query view",
        annotations=ToolAnnotations(
            title="Get WebAdmin view",
            read_only_hint=True,
            open_world_hint=True,
        ),
    )
    async def get_webadmin_view(
        ctx: Context[TimeBaseRuntime],
        view_id: str = Field(description="View identifier"),
        instance_key: InstanceName = None,
    ) -> WebAdminView:
        return await with_tool_errors(
            webadmin_service.get_webadmin_view(
                ctx.request_context.lifespan_context,
                view_id,
                instance_key=instance_key,
            )
        )

    @mcp.tool(
        name="list_webadmin_topics",
        description="List WebAdmin topics",
        annotations=ToolAnnotations(
            title="List WebAdmin topics",
            read_only_hint=True,
            open_world_hint=True,
        ),
    )
    async def list_webadmin_topics(
        ctx: Context[TimeBaseRuntime],
        instance_key: InstanceName = None,
    ) -> WebAdminTopics:
        return await with_tool_errors(
            webadmin_service.list_webadmin_topics(
                ctx.request_context.lifespan_context,
                instance_key=instance_key,
            )
        )

    @mcp.tool(
        name="get_webadmin_topic_schema",
        description="Get the schema of one WebAdmin topic",
        annotations=ToolAnnotations(
            title="Get WebAdmin topic schema",
            read_only_hint=True,
            open_world_hint=True,
        ),
    )
    async def get_webadmin_topic_schema(
        ctx: Context[TimeBaseRuntime],
        topic_id: str = Field(description="Topic identifier"),
        instance_key: InstanceName = None,
    ) -> WebAdminSchema:
        return await with_tool_errors(
            webadmin_service.get_webadmin_topic_schema(
                ctx.request_context.lifespan_context,
                topic_id,
                instance_key=instance_key,
            )
        )

    @mcp.tool(
        name="get_webadmin_background_task_status",
        description="Get background-task status for one stream",
        annotations=ToolAnnotations(
            title="Get WebAdmin background task",
            read_only_hint=True,
            open_world_hint=True,
        ),
    )
    async def get_webadmin_background_task_status(
        ctx: Context[TimeBaseRuntime],
        stream_id: str = Field(description="Stream identifier"),
        instance_key: InstanceName = None,
    ) -> WebAdminBackgroundTask:
        return await with_tool_errors(
            webadmin_service.get_webadmin_background_task_status(
                ctx.request_context.lifespan_context,
                stream_id,
                instance_key=instance_key,
            )
        )

    @mcp.tool(
        name="list_order_book_validation_issues",
        description="List a bounded page of order-book validation report issues",
        annotations=ToolAnnotations(
            title="List order-book validation issues",
            read_only_hint=True,
            open_world_hint=True,
        ),
    )
    async def list_order_book_validation_issues(
        ctx: Context[TimeBaseRuntime],
        report_id: str = Field(description="Validation report identifier"),
        offset: int = Field(default=0, ge=0, description="Zero-based issue offset"),
        rows: int = Field(default=25, ge=1, le=25, description="Issues to return"),
        from_time: str | None = Field(
            default=None,
            description="ISO-8601 lower time bound",
        ),
        to_time: str | None = Field(
            default=None,
            description="ISO-8601 upper time bound",
        ),
        severity: str | None = Field(default=None, description="Severity filter"),
        source_name: str | None = Field(
            default=None,
            description="Source-name filter",
        ),
        symbol: str | None = Field(default=None, description="Symbol filter"),
        instance_key: InstanceName = None,
    ) -> OrderBookValidationIssues:
        return await with_tool_errors(
            webadmin_service.list_order_book_validation_issues(
                ctx.request_context.lifespan_context,
                report_id,
                offset=offset,
                rows=rows,
                from_time=from_time,
                to_time=to_time,
                severity=severity,
                source_name=source_name,
                symbol=symbol,
                instance_key=instance_key,
            )
        )
