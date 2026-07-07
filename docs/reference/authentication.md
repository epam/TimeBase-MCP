# Authentication model

There are two independent directions:

- **Inbound** — protects the MCP HTTP endpoint from MCP clients. Only meaningful for `streamable-http`; local `stdio` has no inbound request to authenticate. Enabled when `MCP_AUTH_AUDIENCE` or `MCP_AUTH_API_KEYS_FILE` is set.
- **Outbound** — controls how MCP connects to TimeBase.

## Auto mode decision order

`auto` (the default) resolves the outbound mode at first connection:

1. If username/password are configured -> `basic`.
2. Else if OAuth2 client credentials are configured -> `oauth2_client_credentials`.
3. Else probe TimeBase OAuth metadata via HTTP `/tb/oauthinfo` endpoint.
4. If TimeBase advertises OAuth and MCP runs remote HTTP with IdP/JWT inbound auth -> `forward_identity`.
5. Else if TimeBase advertises OAuth and MCP uses stdio transport -> `interactive`.
6. Else -> `none`.
