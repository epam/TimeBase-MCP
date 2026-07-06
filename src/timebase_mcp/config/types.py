from typing import Literal

Transport = Literal["stdio", "streamable-http"]
Edition = Literal["community", "enterprise"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
InboundAuthMode = Literal["none", "jwt", "api_key"]
OutboundAuthMode = Literal[
    "auto",
    "none",
    "basic",  # username + password
    "oauth2_client_credentials",  # service account OAuth2 client-credentials
    "forward_identity",  # forward the authenticated caller's bearer token to TimeBase
    "interactive",  # MCP runs an interactive OAuth login to TimeBase's IdP
]

_HTTP_TRANSPORTS: frozenset[Transport] = frozenset({"streamable-http"})
