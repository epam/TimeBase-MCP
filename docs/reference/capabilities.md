# Capabilities

## Tools

| Name | Description | Key inputs |
| - | - | - |
| `list_timebase_instances` | List configured TimeBase instances and descriptions | None |
| `list_streams` | List available TimeBase streams with descriptions | optional `instance_key` |
| `get_stream_schema` | Get the schema of a specific stream | `stream_key`, optional `instance_key` |
| `get_stream_time_range` | Get the UTC time range of a stream | `stream_key`, optional `instance_key` |
| `get_stream_symbols` | Get symbols from a stream (sorted, paginated) | `stream_key`, optional `instance_key`, `limit` (1–500), `cursor` |
| `list_stream_spaces` | List spaces for a specific stream | `stream_key`, optional `instance_key` |
| `get_stream_space_time_range` | Get the UTC time range of a stream space | `stream_key`, `space`, optional `instance_key` |
| `get_stream_messages` | Preview first/last messages from a stream | `stream_key`, optional `instance_key`, `reverse`, `count`, `space` |
| `execute_query` | Execute a TimeBase QQL query (limited preview) | `query`, optional `instance_key`, `limit` (1–100) |
| `compile_query` | Compile a QQL query (parser-level diagnostics only) | `query`, optional `instance_key` |
| `list_qql_functions` | List QQL function signatures supported by the connected TimeBase server | optional `instance_key`, `kind` (`all`, `stateless`, `stateful`), `function_id` |
| `get_timebase_status` | TimeBase version, license, and runtime summary | optional `instance_key` |
| `list_timebase_activity` | Active cursors, loaders, connections, and locks | optional `instance_key`, `kind`, `limit` |
| `get_timebase_activity_detail` | Details for one cursor, loader, connection, or lock | `kind`, `id`, optional `instance_key`, instrument paging |
| `get_server_configuration` | Get MCP server runtime configuration and all configured TimeBase instances | None |

## Resources

Some clients (e.g. VS Code) let you add resources to the context explicitly.

| URI | Name | Description |
| - | - | - |
| `timebase://streams` | `stream_catalog` | Text resource listing streams and descriptions for single-instance setups |
| `timebase://streams/{stream_key}/schema` | `stream_schema` | Resource template exposing a stream schema by key for single-instance setups |
| `timebase://instances/{instance_key}/streams` | `instance_stream_catalog` | Text resource listing streams and descriptions for one instance |
| `timebase://instances/{instance_key}/streams/{stream_key}/schema` | `instance_stream_schema` | Resource template exposing a stream schema by instance and stream key |
