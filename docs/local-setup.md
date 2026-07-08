# Local setup

Manual local `stdio` setup. For Cursor, VS Code, Claude Code or Desktop, [TimeBase Agent Plugins](https://github.com/epam/TimeBase-Agent-Plugins) is recommended. You can also configure those clients manually in [step 3](#3-add-the-server-to-your-mcp-client).

## 1. Install

**Prerequisites:** Python 3.10–3.14 and one of [pip](https://pip.pypa.io/en/stable/installation/), [uv](https://docs.astral.sh/uv/getting-started/installation/), or [pipx](https://pipx.pypa.io/stable/how-to/install-pipx/).

| Tool | Command |
| - | - |
| **uv (recommended)** | `uv tool install -p 3.14 --from "timebase-mcp[all]" timebase-mcp` |
| **pip** | `python -m pip install "timebase-mcp[all]"` |
| **pipx** | `pipx install --python 3.14 "timebase-mcp[all]"` |

The `[all]` extra installs both TimeBase client editions. The server picks the right one per connected instance.

> [!WARNING]
> With **pip**, do not install into a manually created virtual environment. The `timebase-mcp` command must be globally on `PATH` so your MCP client can launch it. Use **pipx** or **uv** if you want isolation (they handle `PATH` automatically). If pip reports an externally-managed environment, use uv or pipx instead.

**Verify** the install (from a new terminal, so `PATH` is fresh):

```bash
timebase-mcp -v
```

### Updating

| Tool | Command |
| - | - |
| **uv** | `uv tool upgrade -p 3.14 timebase-mcp` |
| **pipx** | `pipx upgrade --python 3.14 timebase-mcp` |
| **pip** | `python -m pip install --upgrade "timebase-mcp[all]"` |

Run `timebase-mcp -v` to confirm the new version. Plugin users should update via the [Agent Plugins README](https://github.com/epam/TimeBase-Agent-Plugins#updating-an-existing-plugin-installation).

## 2. Choose how MCP connects to TimeBase

Set these as environment variables in your MCP client config (next step). Pick the row that matches your TimeBase:

| Your TimeBase | Set | Outbound mode |
| - | - | - |
| Unprotected | `TIMEBASE_URL` only | `none` |
| Username / password | `TIMEBASE_URL`, `TIMEBASE_USERNAME`, `TIMEBASE_PASSWORD` | `basic` |
| OAuth | `TIMEBASE_URL` | `interactive` |

With no explicit `TIMEBASE_AUTH_MODE`, the server uses `auto`: it connects anonymously to an unprotected server, and falls back to an interactive browser login when TimeBase advertises OAuth. See [Auto mode decision order](reference/authentication.md#auto-mode-decision-order).

### Interactive redirect URI

Skip to [step 3](#3-add-the-server-to-your-mcp-client) if you are not using OAuth.

Interactive (browser) login is only available for local **stdio** MCP. It opens your IdP's login page in the browser, then MCP captures the result on a **loopback redirect URI**. For stdio, `MCP_HOST` and `MCP_PORT` control this redirect only. They do not start an HTTP server.

Default redirect URI: **`http://127.0.0.1:8000/`** (`MCP_HOST=127.0.0.1`, `MCP_PORT=8000`).

To check the URI MCP uses:

- Check MCP stderr when login starts (`OAuth callback URI: ...`)
- Ask an LLM to use the `get_server_configuration` tool and read `oauth_redirect_uri`

Your IdP must allow that exact URI on the OAuth client (host, port, path, and trailing slash must match character-for-character).

- **Option A: Register MCP's redirect URI (recommended).** Keep the defaults and ask your IdP admin to add `http://127.0.0.1:8000/` to the OAuth client's allowed redirect URIs.

- **Option B: Match an existing TimeBase Admin redirect.** If you reuse the same OAuth client as TimeBase Desktop Admin, align MCP to the redirect URI already registered for Admin (usually `http://localhost:4278/`, confirm in your IdP client settings):

```json
{
  "env": {
    "TIMEBASE_URL": "dxtick://localhost:8011",
    "MCP_HOST": "localhost",
    "MCP_PORT": "4278"
  }
}
```

> [!WARNING]
> MCP binds a short-lived loopback listener on that port during login. If TimeBase Desktop Admin is running and already holds the port, close Admin first or use Option A.

## 3. Add the server to your MCP client

Pick your client below. For all available configuration options, see [Environment variables](reference/environment-variables.md).

<details>
<summary>VS Code</summary>

Create `.vscode/mcp.json`:

```json
{
  "servers": {
    "timebase-mcp": {
      "type": "stdio",
      "command": "timebase-mcp",
      "args": [],
      "env": {
        "TIMEBASE_URL": "dxtick://localhost:8011"
      }
    }
  }
}
```

</details>

<details>
<summary>Cursor</summary>

#### Click the button to install

[![Install MCP Server](https://cursor.com/deeplink/mcp-install-dark.svg)](https://cursor.com/en-US/install-mcp?name=timebase-mcp&config=eyJ0eXBlIjoic3RkaW8iLCJlbnYiOnsiVElNRUJBU0VfVVJMIjoiZHh0aWNrOi8vbG9jYWxob3N0OjgwMTEifSwiY29tbWFuZCI6InRpbWViYXNlLW1jcCAifQ%3D%3D)

#### Or manually create `.cursor/mcp.json`

```json
{
  "mcpServers": {
    "timebase-mcp": {
      "type": "stdio",
      "command": "timebase-mcp",
      "args": [],
      "env": {
        "TIMEBASE_URL": "dxtick://localhost:8011"
      }
    }
  }
}
```

</details>

<details>
<summary>Claude Desktop</summary>

Follow the [official guide](https://modelcontextprotocol.io/docs/develop/connect-local-servers#installing-the-filesystem-server) for your OS, for the configuration use the following:

```json
{
  "mcpServers": {
    "timebase-mcp": {
      "command": "timebase-mcp",
      "args": [],
      "env": {
        "TIMEBASE_URL": "dxtick://localhost:8011"
      }
    }
  }
}
```

</details>

<details>
<summary>Claude Code</summary>

```bash
claude mcp add timebase-mcp --transport stdio --env TIMEBASE_URL='dxtick://localhost:8011' -- timebase-mcp
```

> [!NOTE]
> This adds a `local`-scoped server (current project + user). Use `--scope project|user` for other scopes. See the [official docs](https://code.claude.com/docs/en/mcp#mcp-installation-scopes) for more details.

</details>

<details>
<summary>Opencode</summary>

Add the following to your `opencode.jsonc`:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "timebase-mcp": {
      "type": "local",
      "command": "timebase-mcp",
      "enabled": true,
      "environment": {
        "TIMEBASE_URL": "dxtick://localhost:8011",
      },
    },
  },
}
```

</details>

## 4. Verify

Restart/reload your client and ask the agent to list TimeBase streams. If something fails, see [Troubleshooting](troubleshooting.md).
