# TimeBase MCP

A [Model Context Protocol](https://modelcontextprotocol.io/introduction) server that lets a coding agent (Claude Code, VS Code, Cursor, Claude Desktop, etc.) explore and query [TimeBase](https://kb.timebase.info): list streams, read schemas and symbols, preview messages, run QQL queries, and inspect server status and activity.

The server can run two ways:

- **Locally**, your agent launches `timebase-mcp` as a local process (`stdio`) that connects to your TimeBase.
- **Remotely**, you deploy `timebase-mcp` as a shared HTTP service that multiple users connect their agents to.

## Which guide do I need?

| You want to | Go to |
| - | - |
| Use TimeBase MCP locally (Cursor, VS Code, Claude Code) | [Agent Plugins Quickstart](https://github.com/epam/TimeBase-Agent-Plugins#quickstart) |
| Manual local setup | [Local setup](docs/local-setup.md) |
| Deploy a shared remote MCP server | [Remote deployment](docs/remote-deployment.md) |
| Connect to a running remote server | [Connect to a remote server](docs/connect-remote.md) |

## Documentation

| Topic | Go to |
| - | - |
| Updating | [Local setup: Updating](docs/local-setup.md#updating) |
| Troubleshooting | [Troubleshooting](docs/troubleshooting.md) |
| Reference | [Environment variables, auth, capabilities](docs/reference/README.md) |

## See also

- [TimeBase Agent Plugins](https://github.com/epam/TimeBase-Agent-Plugins)
