# Protecting TimeBase

Agents connected through MCP can read your data, and unless you configure otherwise they can also change it. This page describes what the MCP server can and cannot enforce, and how to set up a deployment where an agent cannot damage TimeBase.

## Recommended setup

Ordered strongest first. The TimeBase-side options are the ones an agent cannot reconfigure.

| Do this | Why |
| - | - |
| Set `TimeBase.readOnly=true` on the TimeBase server | Server-wide read-only mode that prevents any change from any client. Use it when nothing needs to write to that server |
| Give MCP a TimeBase account with `READ` permission only | Same protection scoped to one account, when other clients must keep writing. See [User Access Control](https://kb.timebase.info/docs/development/tools/uac) |
| Enable `read_only` MCP server setting | Blocks modification through MCP tools. |
| Run MCP as a shared remote server | Puts everything on a host the agent cannot reach. See [Remote deployment](../remote-deployment.md) |
| Point agents at a copy or a dedicated analytics instance, not production | Moves risk away from production instance. |

## What the MCP read-only flag covers

Two layers apply when an instance is read-only:

- The TimeBase connection is opened in read-only mode, so the client library refuses the write APIs.
- `execute_query` tool accepts `SELECT` statements only.

## What the MCP read-only flag does not cover

> [!WARNING]
> **A read-only MCP instance is not a read-only TimeBase.** The flag constrains this process. An agent that can run commands or edit files on the machine has several ways around it.

- **Client code the agent writes.** [TimeBase Agent Plugins](https://github.com/epam/TimeBase-Agent-Plugins) ships client skills. Code written with them connects to TimeBase on its own. Review write paths in generated code before running it.
- **Editing the MCP client config.** `read_only` lives in MCP config file. Removing it or adding a second entry for the same URL without it, restores full QQL.
- **Editing the server sources.** When `timebase-mcp` runs from a checkout or a writable install, the enforcement is a few lines of Python.
- **Choosing the wrong instance.** With several instances configured, the agent picks `instance_key` itself. Name them so the intended one is obvious, and do not leave a writable instance pointing at production.

A remote deployment closes the config and source bullets, because a local agent cannot reach what lives on the MCP host. Client code it writes locally still connects to TimeBase directly, unless TimeBase is only reachable from that host.

`TimeBase.readOnly` or a `READ`-only account closes all of them.

## Untrusted content from TimeBase

Whatever is stored in TimeBase reaches the model: stream descriptions, schemas, symbol and space names, query and message values, and the user and application names in the monitoring tools.

Anyone who can write to a stream can therefore place text in an agent's context, including the context of an agent whose instance is read-only. Treat stream content as data, never as instructions, and be deliberate about which agents read streams that untrusted parties can write.

## Limiting resource impact

An agent does not need write access to disrupt TimeBase. A broad query is expensive whether or not it modifies anything.

MCP settings bound interactions with TimeBase:

- `MCP_MAX_CONCURRENT_OPS` caps TimeBase operations in flight. It defaults to `0`, meaning unlimited, and one agent session can call tools in parallel.
- `MCP_OPERATION_TIMEOUT_SECONDS` (default `60`) caps how long this process waits for an operation, and frees the connection when it fires.

You may also want to bound the work on the TimeBase server as well, but these settings apply to every client, not just MCP:

| Setting | Default | What it bounds |
| - | - | - |
| `TimeBase.qql.maxGroupsCount` | `1000000` | Groups a `GROUP BY` may produce |
| `TimeBase.qql.maxWindowSize` | `1000000` | Size of a QQL window function |
| `TimeBase.maxConnections` | `100` | Concurrent connections the server accepts |
| `TimeBase.maxBandwidth` | - | Throughput the server will serve, as an EMA |

Full list in the TimeBase [Configuration](https://kb.timebase.info/docs/deployment/config) reference.
