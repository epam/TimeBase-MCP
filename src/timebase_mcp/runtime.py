from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from timebase_mcp.config import MCPSettings
from timebase_mcp.instance import (
    DEFAULT_INSTANCE_KEY,
    TimeBaseInstanceConfig,
    TimeBaseInstanceRuntime,
)
from timebase_mcp.pool import TimeBaseOperationBudget


@dataclass(slots=True)
class TimeBaseRuntime:
    """Shared server runtime state attached to MCP lifespan."""

    server_settings: MCPSettings
    operation_budget: TimeBaseOperationBudget
    instances: dict[str, TimeBaseInstanceRuntime] = field(default_factory=dict)
    default_instance_key: str = DEFAULT_INSTANCE_KEY

    @classmethod
    def from_settings(cls, settings: MCPSettings) -> TimeBaseRuntime:
        operation_budget = TimeBaseOperationBudget(settings.max_concurrent_ops)
        default_key = settings.resolved_default_instance_key
        instances: dict[str, TimeBaseInstanceRuntime] = {}
        interactive_redirect_uri = settings.resolved_interactive_redirect_uri
        for server in settings.resolve_servers():
            instance_key = server.instance_key
            instances[instance_key] = TimeBaseInstanceRuntime(
                key=instance_key,
                config=TimeBaseInstanceConfig.from_server_config(server),
                interactive_redirect_uri=interactive_redirect_uri,
                runtime_auth_enabled=settings.inbound_auth_enabled,
                runtime_is_http_transport=settings.is_http_transport,
                runtime_inbound_auth_mode=settings.inbound_auth_mode,
                runtime_is_remote_http_bind=settings.is_remote_http_bind,
                resolved_edition=(
                    settings.detected_edition if instance_key == default_key else None
                ),
                operation_budget=operation_budget,
            )
        return cls(
            server_settings=settings,
            operation_budget=operation_budget,
            instances=instances,
            default_instance_key=default_key,
        )

    def get_instance(self, key: str | None = None) -> TimeBaseInstanceRuntime:
        resolved_key = key or self.default_instance_key
        instance = self.instances.get(resolved_key)
        if instance is None:
            available = ", ".join(self.instances) or "<none>"
            raise ValueError(
                f"Unknown TimeBase instance: {resolved_key}. "
                f"Available instances: {available}."
            )

        return instance

    @property
    def default_instance(self) -> TimeBaseInstanceRuntime:
        return self.get_instance()

    async def aclose(self) -> None:
        if not self.instances:
            return

        await asyncio.gather(
            *(instance.aclose() for instance in self.instances.values())
        )


def build_runtime(settings: MCPSettings) -> TimeBaseRuntime:
    """Build the lifespan-owned runtime state from startup settings."""

    return TimeBaseRuntime.from_settings(settings)
