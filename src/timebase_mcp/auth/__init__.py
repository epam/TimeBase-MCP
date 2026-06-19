"""Authentication support for the TimeBase MCP server.

Two independent directions are handled here:

- Inbound: protecting the MCP endpoint as an OAuth 2.0 Resource Server that
  validates the caller's bearer token.
- Outbound: obtaining a TimeBase credential on behalf of the caller, including
  the interactive OAuth login used by local deployments.
"""

from timebase_mcp.auth.principal import Principal, current_principal

__all__ = ["Principal", "current_principal"]
