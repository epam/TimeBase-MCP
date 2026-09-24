# Multi-server TimeBase configuration

Connect one `timebase-mcp` process to multiple TimeBase servers. The server exposes `list_timebase_instances` tool, agents call it and pass the relevant instance key to the tool calls. When multiple instances are configured, omitting `instance_key` results in an error to avoid reading from the wrong TimeBase server.

| Where you configure | How |
| - | - |
| Remote / Docker | `TIMEBASE_SERVERS=/path/to/servers.json` |
| Local MCP client (hand-edited) | Indexed env vars: `TIMEBASE_SERVERS_0_URL`, ... |
| Local MCP client (rich config) | Edit a JSON file -> `timebase-mcp servers-print file.json` -> paste into `TIMEBASE_SERVERS` |

Single-instance connection variables cannot be combined with multi-server configuration.

Per-server native TimeBase OAuth requires a JSON string or file. Indexed env supports URL, name, description, TimeBase basic auth, and `read_only`. [Optional WebAdmin settings](#optional-webadmin-settings) are configured separately for each instance.

## File

See [`timebase-servers.json` example](../examples/timebase-servers.json).

```dotenv
TIMEBASE_SERVERS=/etc/timebase-mcp/servers.json
```

## Indexed env

```json
{
  "mcpServers": {
    "timebase": {
      "type": "stdio",
      "command": "timebase-mcp",
      "env": {
        "TIMEBASE_SERVERS_0_URL": "dxtick://localhost:8011",
        "TIMEBASE_SERVERS_0_NAME": "enterprise",
        "TIMEBASE_SERVERS_0_DESCRIPTION": "Enterprise TimeBase",
        "TIMEBASE_SERVERS_1_URL": "dxtick://localhost:8012",
        "TIMEBASE_SERVERS_1_NAME": "community"
      }
    }
  }
}
```

Indices must be contiguous starting at `0`. Do not set `TIMEBASE_SERVERS` when using indexed vars.

| Indexed env var | Server field |
| - | - |
| `TIMEBASE_SERVERS_{n}_URL` | `url` (required) |
| `TIMEBASE_SERVERS_{n}_NAME` | `name` |
| `TIMEBASE_SERVERS_{n}_DESCRIPTION` | `description` |
| `TIMEBASE_SERVERS_{n}_USERNAME` | `username` |
| `TIMEBASE_SERVERS_{n}_PASSWORD` | `password` |
| `TIMEBASE_SERVERS_{n}_READ_ONLY` | `read_only` |

## JSON string

```bash
timebase-mcp servers-print docs/examples/timebase-servers.json
```

Paste the output as the `TIMEBASE_SERVERS` value in `mcp.json`:

```json
"TIMEBASE_SERVERS": "[{\"name\":\"enterprise\",\"description\":\"Enterprise TimeBase\",\"url\":\"dxtick://localhost:8011\"}]"
```

## Optional WebAdmin settings

WebAdmin settings belong to the same indexed entry or JSON server object as the native connection. Each instance can have its own WebAdmin URL and credentials. Instances without WebAdmin settings retain their native TimeBase tools.

| Indexed env var | JSON server field |
| - | - |
| `TIMEBASE_SERVERS_{n}_WEBADMIN_URL` | `webadmin_url` |
| `TIMEBASE_SERVERS_{n}_WEBADMIN_AUTH_MODE` | `webadmin_auth_mode` |
| `TIMEBASE_SERVERS_{n}_WEBADMIN_USERNAME` | `webadmin_username` |
| `TIMEBASE_SERVERS_{n}_WEBADMIN_PASSWORD` | `webadmin_password` |
| `TIMEBASE_SERVERS_{n}_WEBADMIN_CLIENT_ID` | `webadmin_client_id` |
| `TIMEBASE_SERVERS_{n}_WEBADMIN_CLIENT_SECRET` | `webadmin_client_secret` |
| `TIMEBASE_SERVERS_{n}_WEBADMIN_ISSUER_URL` | `webadmin_issuer_url` |
| `TIMEBASE_SERVERS_{n}_WEBADMIN_SCOPE` | `webadmin_scope` |
| `TIMEBASE_SERVERS_{n}_WEBADMIN_REDIRECT_URI` | `webadmin_redirect_uri` |
| `TIMEBASE_SERVERS_{n}_WEBADMIN_TOKEN_URL` | `webadmin_token_url` |
| `TIMEBASE_SERVERS_{n}_WEBADMIN_TOKEN_FILE` | `webadmin_token_file` |
| `TIMEBASE_SERVERS_{n}_WEBADMIN_API_KEY` | `webadmin_api_key` |
| `TIMEBASE_SERVERS_{n}_WEBADMIN_API_SECRET` | `webadmin_api_secret` |
| `TIMEBASE_SERVERS_{n}_WEBADMIN_PRIVATE_KEY_FILE` | `webadmin_private_key_file` |
| `TIMEBASE_SERVERS_{n}_WEBADMIN_SESSION_LOGIN_ROOT` | `webadmin_session_login_root` |

Defaults and credential combinations match the [WebAdmin environment settings](environment-variables.md#optional-webadmin-connection-and-authentication). Interactive callbacks use a distinct registered port for each concurrent login.
