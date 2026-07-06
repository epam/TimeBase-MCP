from __future__ import annotations

from timebase_mcp.auth.principal import current_principal
from timebase_mcp.clients.factory import get_detected_edition
from timebase_mcp.config.env import (
    dxapi_ssl_termination_enabled,
    dxapi_ssl_trust_all_enabled,
)
from timebase_mcp.models.core import MCPServerConfiguration, TimeBaseServerConfiguration
from timebase_mcp.runtime.instance import TimeBaseInstanceRuntime
from timebase_mcp.runtime.state import TimeBaseRuntime
from timebase_mcp.version import get_version


def timebase_server_configuration(
    instance: TimeBaseInstanceRuntime,
) -> TimeBaseServerConfiguration:
    config = instance.config
    return TimeBaseServerConfiguration(
        name=instance.key,
        description=config.description,
        url=config.tb_url,
        username=config.tb_username,
        edition=get_detected_edition(instance),
        outbound_auth_mode=config.auth_mode,
        http_url=config.http_base_url,
        dxapi_ssl_termination=dxapi_ssl_termination_enabled(),
        dxapi_ssl_trust_all=dxapi_ssl_trust_all_enabled(),
    )


def build_server_configuration(runtime: TimeBaseRuntime) -> MCPServerConfiguration:
    server_settings = runtime.server_settings
    principal = current_principal()

    return MCPServerConfiguration(
        version=get_version(),
        transport=server_settings.transport,
        inbound_auth_mode=server_settings.inbound_auth_mode,
        principal=(
            (principal.username or principal.subject) if principal is not None else None
        ),
        oauth_redirect_uri=server_settings.resolved_interactive_redirect_uri,
        timebase_instances=[
            timebase_server_configuration(instance)
            for instance in runtime.instances.values()
        ],
    )
