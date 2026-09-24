# Authentication model

MCP has inbound authentication for its HTTP endpoint and separate outbound authentication for each backend connection.

| Connection | Authentication | Identity used |
| - | - | - |
| MCP client to MCP | JWT or MCP API key on `streamable-http`; no inbound authentication on local `stdio` | The MCP caller |
| MCP to native TimeBase | `TIMEBASE_AUTH_MODE` and native TimeBase credentials | The caller with `forward_identity`, or the configured native identity |
| MCP to WebAdmin, when configured | Independent WebAdmin credentials | The configured WebAdmin identity, shared by callers of that instance |

## Inbound MCP authentication

On `streamable-http`, inbound authentication is enabled when `MCP_AUTH_AUDIENCE` or `MCP_AUTH_API_KEYS_FILE` is set. JWT authentication validates caller tokens. MCP API-key authentication validates bearer keys against the configured hashed key store.

Inbound authentication controls access to MCP. It does not supply WebAdmin credentials. The [environment reference](environment-variables.md#inbound-mcp-authentication) lists the inbound settings.

## Native TimeBase authentication

Native `forward_identity` forwards the authenticated caller's JWT to TimeBase. MCP and TimeBase must accept the same token audience. Other native modes use separately configured credentials or anonymous access.

## Auto mode decision order

`auto`, the default, resolves the native TimeBase outbound mode at first connection:

1. If username/password are configured -> `basic`.
2. Else if OAuth2 client credentials are configured -> `oauth2_client_credentials`.
3. Else probe TimeBase OAuth metadata via HTTP `/tb/oauthinfo` endpoint.
4. If TimeBase advertises OAuth and MCP runs remote HTTP with IdP/JWT inbound auth -> `forward_identity`.
5. Else if TimeBase advertises OAuth and MCP uses stdio transport -> `interactive`.
6. Else -> `none`.

## Optional WebAdmin authentication

WebAdmin credentials and authentication state are configured per instance. On remote MCP, all callers of an instance use that WebAdmin identity's permissions. Native `forward_identity` does not apply to WebAdmin, and inbound MCP API keys do not sign WebAdmin requests.

WebAdmin browser sessions belong to its frontend. MCP does not reuse those cookies or perform BFF browser login. Its interactive OAuth mode acquires a separate API token and requires local `stdio`.

The [WebAdmin reference](webadmin.md#authentication-compatibility) describes supported authentication methods and deployment restrictions.
