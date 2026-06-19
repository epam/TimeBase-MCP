import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from mcp.server.auth.provider import TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP

from timebase_mcp.auth.inbound import build_inbound_auth
from timebase_mcp.config import MCPSettings
from timebase_mcp.constants import APP_NAME
from timebase_mcp.instructions import SERVER_INSTRUCTIONS
from timebase_mcp.resources import register_resources
from timebase_mcp.runtime import TimeBaseRuntime, build_runtime
from timebase_mcp.tools import register_tools

logger = logging.getLogger(__name__)


def _resolve_inbound_auth(
    settings: MCPSettings,
) -> tuple[AuthSettings | None, TokenVerifier | None]:
    """Resolve inbound auth for the configured transport.

    Inbound auth is only applicable to HTTP transports.
    """
    if not settings.is_http_transport:
        return None, None

    if settings.inbound_auth_enabled:
        inbound = build_inbound_auth(settings)
        if inbound is not None:
            return inbound.auth_settings, inbound.token_verifier
        return None, None

    if settings.is_remote_http_bind:
        logger.warning(
            "Starting an unauthenticated HTTP MCP server on non-loopback host '%s'. "
            "Configure MCP_AUTH_AUDIENCE or MCP_AUTH_API_KEYS_FILE, or ensure "
            "an upstream proxy or gateway enforces authentication.",
            settings.host,
        )

    return None, None


def create_server(settings: MCPSettings) -> FastMCP[TimeBaseRuntime]:
    @asynccontextmanager
    async def lifespan(_: FastMCP[TimeBaseRuntime]) -> AsyncIterator[TimeBaseRuntime]:
        runtime = build_runtime(settings)
        try:
            yield runtime
        finally:
            await runtime.aclose()

    auth_settings, token_verifier = _resolve_inbound_auth(settings)

    mcp = FastMCP(
        name=APP_NAME,
        instructions=SERVER_INSTRUCTIONS,
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level,
        lifespan=lifespan,
        auth=auth_settings,
        token_verifier=token_verifier,
    )
    register_tools(mcp)
    register_resources(mcp)
    return mcp
