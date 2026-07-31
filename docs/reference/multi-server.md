# Multi-server TimeBase configuration

Connect one `timebase-mcp` process to multiple TimeBase servers. The server exposes `list_timebase_instances` tool, agents call it and pass the relevant instance key to the tool calls. When multiple instances are configured, omitting `instance_key` results in an error to avoid reading from the wrong TimeBase server.

| Where you configure | How |
| - | - |
| Remote / Docker | `TIMEBASE_SERVERS=/path/to/servers.json` |
| Local MCP client (hand-edited) | Indexed env vars: `TIMEBASE_SERVERS_0_URL`, ... |
| Local MCP client (rich config) | Edit a JSON file -> `timebase-mcp servers-print file.json` -> paste into `TIMEBASE_SERVERS` |

Per-server OAuth stays in **JSON or file** only. Indexed env supports URL, name, description, basic auth (`username` / `password`) and `read_only`.

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
"TIMEBASE_SERVERS": "[{\"name\":\"enterprise\",\"description\":\"Enterprise TimeBase\",\"url\":\"dxtick://localhost:8011\",...}]"
```
