# Environment variables

## Native TimeBase connection and authentication

| Variable | Default | Description |
| - | - | - |
| `TIMEBASE_URL` | `dxtick://localhost:8011` | TimeBase native connection URL. |
| `TIMEBASE_SERVERS` | None | Multi-server list: a JSON array string, a path to a JSON file, or omit and use indexed `TIMEBASE_SERVERS_{n}_*` env vars (see [Multi-server configuration](./multi-server.md)). |
| `TIMEBASE_USERNAME` | None | Username for `basic` auth; optional username override for `oauth2_client_credentials`. |
| `TIMEBASE_PASSWORD` | None | Password for `basic` auth. |
| `TIMEBASE_AUTH_MODE` | `auto` | Outbound mode: `auto`, `none`, `basic`, `oauth2_client_credentials`, `forward_identity`, `interactive`. |
| `TIMEBASE_HTTP_URL` | derived | TimeBase HTTP API base URL, used for OAuth discovery and HTTP diagnostics. MCP derives this from `TIMEBASE_URL` when unset and also tries port `8021` when the native URL uses port default `8011`. Set explicitly for proxies, custom ports, or non-default paths. |
| `TIMEBASE_READ_ONLY` | `false` | Whether TimeBase connections are opened in read-only mode, see [Protecting TimeBase](./protecting-timebase.md). |
| `TIMEBASE_OAUTH2_TOKEN_URL` | None | Token endpoint for outbound service-account client credentials. |
| `TIMEBASE_OAUTH2_CLIENT_ID` | None / discovered | OAuth2 client ID for service-account auth, or a dedicated client-app override for local `interactive` login. |
| `TIMEBASE_OAUTH2_CLIENT_SECRET` | None | OAuth2 client secret for service-account auth. |
| `TIMEBASE_OAUTH2_SCOPE` | discovered / None | OAuth2 scope(s). For service accounts set the provider-required value; for local `interactive`, this may override the discovered login scopes. |
| `TIMEBASE_OAUTH2_TOKEN_PARAMS` | None | JSON object of extra client-credentials token form params. Cannot override reserved fields. |

`dxapi` SSL variables (`DXAPI_SSL_TERMINATION`, `DXAPI_SSL_TRUST_ALL`, `DXAPI_SSL_CERT_FILE`) are read by the TimeBase client library, see [TLS / SSL to TimeBase](../remote-deployment.md#tls--ssl-to-timebase).

## MCP transport

| Variable | Default | Description |
| - | - | - |
| `MCP_TRANSPORT` | `stdio` | Transport: `stdio` or `streamable-http`. |
| `MCP_HOST` | `127.0.0.1` | HTTP bind host. For stdio, the loopback host for native TimeBase interactive login (`http://MCP_HOST:MCP_PORT/`). |
| `MCP_PORT` | `8000` | HTTP bind port (1-65535). For stdio, the loopback port for native TimeBase interactive login. |
| `MCP_ALLOWED_HOSTS` | None | Allowlist of acceptable HTTP `Host` header values, for DNS rebinding protection on `streamable-http`. |
| `MCP_ALLOWED_ORIGINS` | None | Allowlist of acceptable HTTP `Origin` header values, for DNS rebinding protection on `streamable-http`. |

WebAdmin interactive login uses `TIMEBASE_WEBADMIN_REDIRECT_URI` independently of `MCP_HOST` and `MCP_PORT`.

## Inbound MCP authentication

| Variable | Default | Description |
| - | - | - |
| `MCP_AUTH_ISSUER_URL` | discovered | IdP mode: issuer override. Required when TimeBase `/tb/oauthinfo` is empty or for a separate MCP API audience. |
| `MCP_AUTH_JWKS_URL` | discovered | IdP mode: JWKS URL override. If unset, discovered from `/tb/oauthinfo`. |
| `MCP_AUTH_AUDIENCE` | None | IdP mode: expected JWT audience/resource. **Required** for IdP inbound auth. |
| `MCP_AUTH_REQUIRED_SCOPES` | None | Scopes required on inbound tokens. |
| `MCP_AUTH_PUBLIC_URL` | None | IdP mode: public URL of this MCP Resource Server. Required as a public endpoint for non-loopback HTTP binds. |
| `MCP_AUTH_API_KEYS_FILE` | None | Path to a hashed API-key store |

## Operation limits and logging

| Variable | Default | Description |
| - | - | - |
| `MCP_MAX_CONCURRENT_OPS` | `0` | Max concurrent TimeBase operations (`0` disables limits). |
| `MCP_MAX_IDLE_CLIENTS` | `0` (auto) | Max idle TimeBase connections per shared pool. `0` = `max(1, MCP_MAX_CONCURRENT_OPS / 2)`. Per-user `forward_identity` pools always use `0`. |
| `MCP_OPERATION_TIMEOUT_SECONDS` | `60` | Per-operation timeout in seconds (`0` disables). |
| `MCP_LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, or `CRITICAL`. |

## Optional WebAdmin connection and authentication

WebAdmin settings are independent of native TimeBase and inbound MCP authentication. Native TimeBase tools do not require WebAdmin. See the [WebAdmin reference](webadmin.md#identity-and-availability) for tool availability.

| Variable | Default | Description |
| - | - | - |
| `TIMEBASE_WEBADMIN_URL` | None | WebAdmin base URL, for example `http://localhost:8099`. |
| `TIMEBASE_WEBADMIN_AUTH_MODE` | `password` | Explicit selection for `interactive`, `client_credentials`, or `bearer_file`. Password and API-key authentication need no mode setting. |

### Built-in password

Built-in password authentication requires only the WebAdmin URL, username, and password. MCP supplies the OAuth client credentials automatically.

| Variable | Default | Description |
| - | - | - |
| `TIMEBASE_WEBADMIN_USERNAME` | None | WebAdmin username. |
| `TIMEBASE_WEBADMIN_PASSWORD` | None | WebAdmin password. |

### API keys

Set `TIMEBASE_WEBADMIN_API_KEY` with exactly one of `TIMEBASE_WEBADMIN_API_SECRET` or `TIMEBASE_WEBADMIN_PRIVATE_KEY_FILE`. API-key authentication cannot be combined with WebAdmin username, password, or OAuth credentials.

| Variable | Default | Description |
| - | - | - |
| `TIMEBASE_WEBADMIN_API_KEY` | None | WebAdmin API-key name for basic or session authentication. |
| `TIMEBASE_WEBADMIN_API_SECRET` | None | Secret for basic signed WebAdmin requests. |
| `TIMEBASE_WEBADMIN_PRIVATE_KEY_FILE` | None | RSA PEM path for session API keys. |
| `TIMEBASE_WEBADMIN_SESSION_LOGIN_ROOT` | `/session/login` | Local session login path; configure only with a session private-key file. |

### WebAdmin OAuth acquisition

The [WebAdmin authentication reference](webadmin.md#authentication-compatibility) describes mode compatibility and deployment limits.

| Variable | Required by | Description |
| - | - | - |
| `TIMEBASE_WEBADMIN_CLIENT_ID` | `interactive`, `client_credentials` | OAuth client ID. |
| `TIMEBASE_WEBADMIN_CLIENT_SECRET` | `client_credentials` | OAuth client secret. Interactive login uses no secret. |
| `TIMEBASE_WEBADMIN_ISSUER_URL` | `interactive` | Trusted HTTPS issuer. |
| `TIMEBASE_WEBADMIN_SCOPE` | `interactive`, `client_credentials` | Space-separated scopes. |
| `TIMEBASE_WEBADMIN_REDIRECT_URI` | `interactive` | Registered HTTP loopback callback. |
| `TIMEBASE_WEBADMIN_TOKEN_URL` | `client_credentials` | Trusted HTTPS token endpoint. |
| `TIMEBASE_WEBADMIN_TOKEN_FILE` | `bearer_file` | Private API access-token file. |

MCP caches acquired OAuth tokens in memory only.
