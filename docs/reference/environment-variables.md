# Environment variables

| Variable | Default | Description |
| - | - | - |
| `TIMEBASE_URL` | `dxtick://localhost:8011` | TimeBase native connection URL. |
| `TIMEBASE_SERVERS` | None | Multi-server list: a JSON array string, a path to a JSON file, or omit and use indexed `TIMEBASE_SERVERS_{n}_*` env vars (see [Multi-server configuration](#multi-server-timebase-configuration)). |
| `TIMEBASE_USERNAME` | None | Username for `basic` auth; optional username override for `oauth2_client_credentials`. |
| `TIMEBASE_PASSWORD` | None | Password for `basic` auth. |
| `TIMEBASE_AUTH_MODE` | `auto` | Outbound mode: `auto`, `none`, `basic`, `oauth2_client_credentials`, `forward_identity`, `interactive`. |
| `TIMEBASE_HTTP_URL` | derived | TimeBase HTTP API base URL, used for OAuth discovery and HTTP diagnostics. MCP derives this from `TIMEBASE_URL` when unset and also tries port `8021` when the native URL uses port default `8011`. Set explicitly for proxies, custom ports, or non-default paths. |
| `TIMEBASE_OAUTH2_TOKEN_URL` | None | Token endpoint for outbound service-account client credentials. |
| `TIMEBASE_OAUTH2_CLIENT_ID` | None / discovered | OAuth2 client ID for service-account auth, or a dedicated client-app override for local `interactive` login. |
| `TIMEBASE_OAUTH2_CLIENT_SECRET` | None | OAuth2 client secret for service-account auth. |
| `TIMEBASE_OAUTH2_SCOPE` | discovered / None | OAuth2 scope(s). For service accounts set the provider-required value; for local `interactive`, this may override the discovered login scopes. |
| `TIMEBASE_OAUTH2_TOKEN_PARAMS` | None | JSON object of extra client-credentials token form params. Cannot override reserved fields. |
| `MCP_TRANSPORT` | `stdio` | Transport: `stdio` or `streamable-http`. |
| `MCP_HOST` | `127.0.0.1` | HTTP bind host. For stdio, also the loopback host used for interactive OAuth redirect (`http://MCP_HOST:MCP_PORT/`). |
| `MCP_PORT` | `8000` | HTTP bind port (1–65535). For stdio, also the loopback port used for interactive OAuth redirect. |
| `MCP_MAX_CONCURRENT_OPS` | `0` | Max concurrent TimeBase operations (`0` disables limits). |
| `MCP_MAX_IDLE_CLIENTS` | `0` (auto) | Max idle TimeBase connections per shared pool. `0` = `max(1, MCP_MAX_CONCURRENT_OPS / 2)`. Per-user `forward_identity` pools always use `0`. |
| `MCP_OPERATION_TIMEOUT_SECONDS` | `0` | Per-operation timeout in seconds (`0` disables). |
| `MCP_AUTH_ISSUER_URL` | discovered | IdP mode: issuer override. Required when TimeBase `/tb/oauthinfo` is empty or for a separate MCP API audience. |
| `MCP_AUTH_JWKS_URL` | discovered | IdP mode: JWKS URL override. If unset, discovered from `/tb/oauthinfo`. |
| `MCP_AUTH_AUDIENCE` | None | IdP mode: expected JWT audience/resource. **Required** for IdP inbound auth. |
| `MCP_AUTH_REQUIRED_SCOPES` | None | Scopes required on inbound tokens. |
| `MCP_AUTH_PUBLIC_URL` | None | IdP mode: public URL of this MCP Resource Server. Required as a public endpoint for non-loopback HTTP binds. |
| `MCP_AUTH_API_KEYS_FILE` | None | Path to a hashed API-key store |
| `MCP_LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, or `CRITICAL`. |

`dxapi` SSL variables (`DXAPI_SSL_TERMINATION`, `DXAPI_SSL_TRUST_ALL`, `DXAPI_SSL_CERT_FILE`) are read by the TimeBase client library, see [TLS / SSL to TimeBase](../remote-deployment.md#tls--ssl-to-timebase).
