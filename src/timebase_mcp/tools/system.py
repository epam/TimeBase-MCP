import os

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.session import ServerSession
from mcp.types import ToolAnnotations

from timebase_mcp.auth.discovery import derive_http_base_urls
from timebase_mcp.auth.principal import current_principal
from timebase_mcp.clients.factory import get_detected_edition
from timebase_mcp.models import MCPServerConfiguration, TimeBaseInstanceInfo
from timebase_mcp.runtime import TimeBaseRuntime


def register_system_tools(mcp: FastMCP) -> None:

    @mcp.tool(
        name="list_timebase_instances",
        description="List configured TimeBase server instances.",
        annotations=ToolAnnotations(
            title="List TimeBase instances",
            readOnlyHint=True,
            openWorldHint=False,
        ),
    )
    async def list_timebase_instances(
        ctx: Context[ServerSession, TimeBaseRuntime],
    ) -> list[TimeBaseInstanceInfo]:
        runtime = ctx.request_context.lifespan_context
        return [
            TimeBaseInstanceInfo(
                name=instance.key,
                description=instance.config.description,
                is_default=instance.key == runtime.default_instance_key,
            )
            for instance in runtime.instances.values()
        ]

    @mcp.tool(
        name="get_server_configuration",
        description="Get the MCP server runtime configuration, including detected TimeBase server edition and connection parameters. "
        "Edition being None indicates that it has not been inferred from configuration or no successful connection to TimeBase has been made yet.",
        annotations=ToolAnnotations(
            title="Get MCP server configuration",
            readOnlyHint=True,
            openWorldHint=False,
        ),
    )
    async def get_server_configuration(
        ctx: Context[ServerSession, TimeBaseRuntime],
    ) -> MCPServerConfiguration:
        runtime = ctx.request_context.lifespan_context
        default_instance = runtime.default_instance
        server_settings = runtime.server_settings
        instance_config = default_instance.config
        principal = current_principal()
        tb_http_urls = (
            [instance_config.http_base_url]
            if instance_config.http_base_url is not None
            else list(derive_http_base_urls(instance_config.tb_url))
        )

        return MCPServerConfiguration(
            transport=server_settings.transport,
            tb_url=instance_config.tb_url,
            tb_username=instance_config.tb_username,
            edition=get_detected_edition(default_instance),
            inbound_auth_enabled=(
                server_settings.inbound_auth_enabled
                and server_settings.is_http_transport
            ),
            outbound_auth_mode=instance_config.auth_mode,
            principal=(
                (principal.username or principal.subject)
                if principal is not None
                else None
            ),
            tb_http_urls=tb_http_urls,
            oauth_redirect_uri=server_settings.resolved_interactive_redirect_uri,
            dxapi_ssl_termination=(
                os.environ.get("DXAPI_SSL_TERMINATION", "").casefold() == "true"
            ),
            dxapi_ssl_trust_all=(
                os.environ.get("DXAPI_SSL_TRUST_ALL", "").casefold() == "true"
            ),
        )

    _ = (list_timebase_instances, get_server_configuration)
