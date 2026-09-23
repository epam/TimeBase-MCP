# WebAdmin reference

WebAdmin is an optional connection for each TimeBase instance. MCP provides read-only inspection of views, topics, background tasks, and existing order-book validation reports. The [capabilities reference](capabilities.md#webadmin-inspection) lists the tools. Administrative workflows, exports, and STOMP subscriptions require a separate client.

For configuration steps, see [Add WebAdmin access](../webadmin-setup.md). The [environment reference](environment-variables.md#optional-webadmin-connection-and-authentication) lists settings, and the [multi-server reference](multi-server.md#optional-webadmin-settings) lists per-instance mappings.

## Identity and availability

| Aspect | Behavior |
| - | - |
| WebAdmin identity | WebAdmin uses its own URL and credentials. Native TimeBase credentials, inbound MCP API keys, and WebAdmin browser cookies are not reused. |
| Remote MCP | All callers share the configured WebAdmin identity for each instance. Native `forward_identity` applies only to TimeBase. |
| Tool registration | WebAdmin tools are advertised when at least one instance has a WebAdmin URL. The selected instance must have its own WebAdmin URL. Temporary service failure does not remove tools from the catalog. |
| Public metadata | `get_webadmin_info` calls public version and authentication endpoints. A successful result does not verify protected access. |

## Authentication compatibility

WebAdmin discovery reports `provider_type`. MCP's `TIMEBASE_WEBADMIN_AUTH_MODE` selects token acquisition; API-key settings select signed requests independently of `provider_type`.

| Server mechanism | MCP credentials or mode | Compatibility |
| - | - | - |
| `BUILT_IN_OAUTH` | Username and password | MCP supplies the standard OAuth client credentials. |
| Basic API key | Key and secret | Signed REST requests; server-side API-key sessions must be disabled. |
| Session API key | Key and private-key file | Session login and ordered signed REST requests. |
| `SSO` | `interactive`, `client_credentials`, or `bearer_file` | Requires a token accepted by the deployment's API and authorization rules. |
| `SSO_BFF` | A bearer mode with an accepted API token | Frontend browser-cookie sessions do not authenticate MCP requests. |
| `EXTERNAL_OAUTH` | `interactive`, `client_credentials`, or `bearer_file` | The provider name does not establish which grants or tokens the deployment accepts. |

### Shared bearer requirements

The `interactive`, `client_credentials`, and `bearer_file` modes require an HTTPS WebAdmin URL outside loopback and reject unknown discovery providers. WebAdmin decides whether the token's signature, issuer, audience, scopes, and roles authorize a request. Acquiring a token does not establish API access.

WebAdmin REST, OIDC discovery, and token requests do not follow redirects. HTTPS certificate verification remains enabled even when `DXAPI_SSL_TRUST_ALL` is set. WebAdmin base URLs may include a deployment context path, but not credentials, a query string, or a fragment.

### Built-in password

MCP supplies standard OAuth client credentials. Custom deployments can set `TIMEBASE_WEBADMIN_CLIENT_ID` and `TIMEBASE_WEBADMIN_CLIENT_SECRET` together. The discovered token endpoint must use the configured WebAdmin origin.

MCP caches the access token in memory and reacquires it when it expires. The password grant does not use refresh tokens.

### Interactive login

| Aspect | Behavior |
| - | - |
| Transport and grant | Local `stdio` only; authorization code with S256 PKCE and state validation. |
| Callback | Binds to `localhost` or `127.0.0.1`; login waits at most five minutes. |
| Discovery | WebAdmin's `config_url` must match the configured issuer plus `/.well-known/openid-configuration`. `SSO_BFF` and `EXTERNAL_OAUTH` may omit `config_url`; a conflicting value is rejected. |
| OIDC endpoints | Metadata must report the configured issuer. Authorization and token endpoints must share the issuer's HTTPS origin; split-origin providers are unsupported. |
| Token lifecycle | Access and refresh tokens stay in memory per instance. A request refreshes a token near expiry. Rejected refresh starts a new login. Restarting MCP requires another login. |

### Client credentials

MCP posts `client_id` and `client_secret` to the configured HTTPS token endpoint using `client_secret_post`. It caches the access token in memory and reacquires it when it expires. This mode does not use OIDC discovery or `config_url` matching, and it rejects `TIMEBASE_WEBADMIN_ISSUER_URL`.

### Bearer-token file

MCP reads one ASCII access token from a private file before each protected request. The file may end with one newline and has a 32 KiB limit. Atomic replacement rotates the token without restarting MCP; the external token manager owns acquisition and expiry recovery. This mode does not use OIDC discovery or `config_url` matching, and it rejects `TIMEBASE_WEBADMIN_ISSUER_URL`.

### Basic API keys

MCP signs each protected GET with HMAC-SHA384. Public discovery is unsigned. Basic keys have no session nonce or token-refresh lifecycle. Updating the configured secret after server-side rotation requires an MCP restart.

### Session API keys

| Aspect | Behavior |
| - | - |
| Private key | Unencrypted RSA PEM, at least 2048 bits. |
| Login root | `/session/login` by default. The path must be local and absolute, without traversal, a query string, or a fragment. |
| Request order | Each instance serializes session acquisition, nonce allocation, and protected GETs. Other instances operate independently. |
| Lifetime | The next protected request after 90% of the local idle interval obtains a replacement session. Responses other than HTTP 400 or 401 extend the local deadline. There is no background keepalive. |
| Rejection | HTTP 400 or 401 clears the session for the next call without retrying the failed request. HTTP 403 preserves the session and reports denied permission. |
| Shutdown | MCP clears local session state. The server cleans up abandoned sessions. |

## Response limits and errors

| Case | Behavior |
| - | - |
| HTTP status | Inspection GETs require HTTP 200. HTTP 206 and other unexpected success statuses are errors. |
| Response size | REST responses, including `/api/v0/authInfo`, have a 128 KiB read limit. Serialized tool results have a separate 128 KiB limit. OIDC discovery, token, and session-login responses have a 32 KiB limit. |
| Views and topics | Sorted and limited to the first 100 items. Results contain `returned_count` and `truncated`; there is no continuation parameter. |
| Validation issues | `offset` and `rows` select up to 25 issues. Results contain `has_more`; `inline_only` and `warning_message` describe report restrictions. |
| HTTP 401 | Cached OAuth authentication is invalidated only if the failed request used the current provider and token. The next call rediscovers the provider. |
| HTTP 403 | Reports insufficient permission without changing the configured identity or the session API key. |
| Failed authentication | MCP does not fall back to native credentials, another configured identity, or browser cookies. |
| Timeout or cancellation | The MCP wait ends. A running HTTP worker retains its concurrency slot until it finishes. An interactive callback may remain active until login finishes or times out. |
