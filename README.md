# TimeBase MCP

<!-- TODO: Replace this README with README.v0.2.md when v0.2 is released -->

> [!NOTE]
> **This README documents v0.1 of the TimeBase MCP.**
>
> Pre-releases are published as `0.2.0rcN` and can be installed with an explicit pin. See [`README.v0.2.md`](README.v0.2.md) for the v0.2 documentation.
>
> For v0.1 code, see the [`v0.1` branch](https://github.com/epam/TimeBase-MCP/tree/v0.1).

## Prerequisites

- Python `>=3.10`
- One of the following:
  - [pip](https://pip.pypa.io/en/stable/installation/)
  - [uv](https://docs.astral.sh/uv/getting-started/installation/)
  - [pipx](https://pipx.pypa.io/stable/how-to/install-pipx/)

## Installation

> [!TIP]
> If you're planning to work with both TimeBase Community and Enterprise servers, you can install both editions by replacing `[enterprise]` with `[all]` in the commands below.
> MCP server will automatically select the correct edition to use based on the connected TimeBase server.
>
> Already installed? See [Updating an Existing Installation](#updating-an-existing-installation).

> [!IMPORTANT]
> Make sure to replace `<user>` and `<password>` with your Nexus credentials when installing the enterprise edition.

### Using pip

Community edition:

```bash
python -m pip install "timebase-mcp[community]"
```

Enterprise edition:

```bash
python -m pip install --extra-index-url "https://<user>:<password>@nexus.deltixhub.com/repository/epm-rtc-public-python/simple" "timebase-mcp[enterprise]"
```

If you get an error about environment being managed externally, follow the [uv](#using-uv) or [pipx](#using-pipx) instructions instead.

> [!WARNING]
> Do NOT create a virtual environment manually when using pip, as MCP server needs to be globally accessible in PATH. If you want to isolate dependencies, use [pipx](#using-pipx) or [uv](#using-uv) which handle this automatically.

### Using uv

Community edition:

```bash
uv tool install -p 3.14 --from "timebase-mcp[community]" timebase-mcp
```

Enterprise edition:

```bash
uv tool install -p 3.14 --index "https://<user>:<password>@nexus.deltixhub.com/repository/epm-rtc-public-python/simple" --from "timebase-mcp[enterprise]" timebase-mcp
```

### Using pipx

Community edition:

```bash
pipx install --python 3.14 "timebase-mcp[community]"
```

Enterprise edition:

```bash
pipx install --python 3.14 --pip-args "--extra-index-url https://<user>:<password>@nexus.deltixhub.com/repository/epm-rtc-public-python/simple" "timebase-mcp[enterprise]"
```

> [!NOTE]
> MCP server will be launched from MCP client (coding agent) automatically, but the installed `timebase-mcp` must be in PATH.
> After installation you can verify that the server is correctly installed and accessible by running the following command from a new terminal:
>
> ```bash
> timebase-mcp -v
> ```

## Updating an Existing Installation

Use the command for your package manager to update `timebase-mcp` to the latest available version.

### Using pip

Community edition:

```bash
python -m pip install --upgrade "timebase-mcp[community]"
```

Enterprise edition:

```bash
python -m pip install --upgrade --extra-index-url "https://<user>:<password>@nexus.deltixhub.com/repository/epm-rtc-public-python/simple" "timebase-mcp[enterprise]"
```

### Using uv

Community edition:

```bash
uv tool upgrade -p 3.14 timebase-mcp
```

Enterprise edition:

```bash
uv tool upgrade -p 3.14 --index "https://<user>:<password>@nexus.deltixhub.com/repository/epm-rtc-public-python/simple" timebase-mcp
```

### Using pipx

Community edition:

```bash
pipx upgrade --python 3.14 "timebase-mcp"
```

Enterprise edition:

```bash
pipx upgrade --python 3.14 --pip-args "--extra-index-url https://<user>:<password>@nexus.deltixhub.com/repository/epm-rtc-public-python/simple" "timebase-mcp"
```

After updating, run `timebase-mcp -v` from a new terminal to verify the installed version and PATH access.

## Basic Configuration

For no-auth and basic-auth setups, use these variables in your MCP config:

| Variable | Default value | Description |
| - | - | - |
| `TIMEBASE_URL` | `dxtick://localhost:8011` | TimeBase connection URL |
| `TIMEBASE_USERNAME` | None | Username for basic auth |
| `TIMEBASE_PASSWORD` | None | Password for basic auth |

If your server does not require authentication, set only `TIMEBASE_URL`.

For more options, including OAuth2, see [Advanced Configuration](#advanced-configuration).

## MCP Client Configuration

Follow the instructions for your MCP client to configure the server.

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

Available options: Claude Desktop config and MCP Bundle.

#### MCP Config

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

#### MCP Bundle

This currently requires [Node.js](https://nodejs.org/en/download) and [uv](https://docs.astral.sh/uv/getting-started/installation/) to be installed.

1. Run the following command in this repo to create the bundle:

```bash
npx @anthropic-ai/mcpb pack
```

2. In Claude Desktop go to `Settings > Extensions > Advanced settings > Install extension` and select the `.mcpb` file generated in step 1.

</details>

<details>
<summary>Claude Code</summary>

```
claude mcp add timebase-mcp --transport stdio --env TIMEBASE_URL='dxtick://localhost:8011' -- timebase-mcp
```

> [!NOTE]
> This command adds a local-scoped server (current project and user only). There're also `project` and `user` scopes, specify them via a `--scope local|project|user` flag.
> Check out the [official documentation](https://code.claude.com/docs/en/mcp#mcp-installation-scopes) for more details.

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

## Advanced Configuration

Use these variables for configuring the MCP server:

| Variable | Default value | Description |
| - | - | - |
| `TIMEBASE_URL` | `dxtick://localhost:8011` | TimeBase connection URL |
| `TIMEBASE_USERNAME` | None | Username for basic auth. Optional for OAuth2; when omitted, defaults to `TIMEBASE_OAUTH2_CLIENT_ID` |
| `TIMEBASE_PASSWORD` | None | Password for basic auth. Mutually exclusive with the OAuth2 settings |
| `TIMEBASE_OAUTH2_TOKEN_URL` | None | OAuth2 token endpoint for auth using the client credentials flow |
| `TIMEBASE_OAUTH2_CLIENT_ID` | None | OAuth2 client ID |
| `TIMEBASE_OAUTH2_CLIENT_SECRET` | None | OAuth2 client secret |
| `TIMEBASE_OAUTH2_SCOPE` | None | Optional space-delimited OAuth2 scopes |
| `TIMEBASE_OAUTH2_TOKEN_PARAMS` | None | Optional JSON object of extra OAuth2 token form parameters |
| `MCP_LOG_LEVEL` | `INFO` | Log verbosity: `DEBUG`, `INFO`, `WARNING`, `ERROR`, or `CRITICAL` |

> [!IMPORTANT]
> Enterprise connections may need extra SSL environment variables that are handled by `dxapi`. This includes `DXAPI_SSL_TERMINATION`, `DXAPI_SSL_TRUST_ALL`, `SSL_CERT_FILE`, etc.
> See [dxapi environment variables](https://kb.timebase.info/docs/development/clients/python%20dxapi/python_dxapi_configuration#environment-variables) and [SSL configuration](https://kb.timebase.info/docs/development/clients/python%20dxapi/python_dxapi_configuration#ssl-configuration).

### OAuth2 Client Credentials

OAuth2 works only with the enterprise `dxapi` client. `timebase-mcp` uses the client credentials flow and currently supports the `client_secret_post` token-endpoint authentication method.

Required variables:

- `TIMEBASE_OAUTH2_TOKEN_URL`
- `TIMEBASE_OAUTH2_CLIENT_ID`
- `TIMEBASE_OAUTH2_CLIENT_SECRET`

Optional variables:

- `TIMEBASE_USERNAME` to override the default TimeBase username; otherwise `TIMEBASE_OAUTH2_CLIENT_ID` is used
- `TIMEBASE_OAUTH2_SCOPE` as a single space-delimited string when multiple scopes are required
- `TIMEBASE_OAUTH2_TOKEN_PARAMS`

Microsoft Entra ID example configuration:

```dotenv
TIMEBASE_URL=dxtick://example.com:8011
TIMEBASE_OAUTH2_TOKEN_URL=https://login.microsoftonline.com/<tenant-id>/oauth2/v2.0/token
TIMEBASE_OAUTH2_CLIENT_ID=<client-id>
TIMEBASE_OAUTH2_CLIENT_SECRET=<client-secret>
TIMEBASE_OAUTH2_SCOPE=api://example-api/.default
```

Use `TIMEBASE_OAUTH2_TOKEN_PARAMS` only if your provider requires extra token fields such as `audience`, `resource`, etc. It must be a valid JSON object.

## Features

### Tools

| Name | Description | Key inputs | Notes |
| - | - | - | - |
| `list_streams` | List available TimeBase streams with descriptions | None | Read-only stream catalog lookup |
| `get_stream_schema` | Get the schema of a specific stream | `stream_key` | Returns the schema text for the requested stream |
| `get_stream_time_range` | Get the UTC time range of a specific stream | `stream_key` | Returns start and end timestamps |
| `get_stream_symbols` | Get symbols from a specific stream | `stream_key`, optional `limit`, optional `cursor` | Returns sorted, paginated symbols. `limit` can be 1-500 |
| `get_stream_messages` | Preview the first or last messages from a stream | `stream_key`, optional `reverse`, optional `count` | Returns up to `count` JSON-formatted messages. Use `reverse` to read from the end of the stream |
| `execute_query` | Execute a TimeBase QQL query | `query`, optional `limit` | Returns a limited preview of result rows. `limit` can be 1-100 |
| `compile_query` | Compile a TimeBase QQL query | `query` | Returns parser-level diagnostics only (not full semantic/logical validation). `error_token` is the first unexpected token, which may be after the actual root cause. |

### Resources

Some clients (e.g. VS Code) allow users to explicitly add resources to the context.

| URI | Name | Description |
| - | - | - |
| `timebase://streams` | `stream_catalog` | Text resource listing streams and descriptions |
| `timebase://streams/{stream_key}/schema` | `stream_schema` | Resource template exposing a stream schema by key |

## Troubleshooting

### General

- Green indicator in Cursor's MCP panel means the timebase-mcp server is running and Cursor is connected to it, but it doesn't necessarily mean that timebase-mcp is successfully connected to TimeBase.

#### Where to find logs?

<details>
<summary>VS Code</summary>

Logs can be found in the output panel (`View > Output`, then select timebase-mcp from the dropdown).

</details>

<details>
<summary>Cursor</summary>

Logs can be found in the Cursor's output panel (`View > Output`, then select timebase-mcp from the dropdown).

</details>

<details>
<summary>Claude Desktop</summary>

Logs can be found at `Settings > Developer > TimeBase MCP > View Logs`.

</details>

<details>
<summary>Claude Code</summary>

Launch Claude Code in an MCP debug mode:

```bash
claude --debug mcp
```

Refer to the [official documentation](https://code.claude.com/docs/en/debug-your-config#check-mcp-servers) for more details.

</details>

<details>
<summary>Opencode</summary>

MCP server logs can be found in the Opencode's log:

- On Linux and MacOS: `~/.local/share/opencode/log/`
- On Windows: Press `WIN+R` and paste `%USERPROFILE%\.local\share\opencode\log`

Refer to the [official documentation](https://opencode.ai/docs/troubleshooting/#logs) for more details.

</details>

<details>
<summary>Other</summary>

Logs are printed to stderr of the `timebase-mcp` process, look for them in the terminal where you started `timebase-mcp` or in the logs of your MCP client.

</details>

### TimeBase connection issues

First, find the logs as described above and check for any error messages related to TimeBase connection. Common issues:

- TimeBase server is not running or not accessible from this environment (e.g. wrong URL, network issues, firewall, WSL misconfiguration, etc.). Look for messages like `Connection refused at SOCKET`.

- MCP edition mismatch: if you're trying to connect to TimeBase Enterprise but have the Community edition installed (or vice versa), you may see errors about protocol version mismatch and message about requiring an Enterprise/Community client.

- Remote access is not enabled: some features require remote access to be enabled on the TimeBase server. Refer to TimeBase documentation for instructions on how to enable it:
  - [Remote Access for TimeBase Enterprise](https://kb.timebase.info/docs/deployment/config#system-remoteMonitoring)
  - [Remote Access for TimeBase Community](https://kb.timebase.info/community/deployment/config#system-remoteMonitoring)

- Missing `DXAPI_SSL_TERMINATION` flag: if your TimeBase server setup requires SSL termination, but the `DXAPI_SSL_TERMINATION` environment variable is not set to `true`, `dxapi` may hang indefinitely and you'll get MCP connection timeout errors in the logs.

For TimeBase CE make sure that both Native (usually 8011) and HTTP (usually 8021) ports are visible and exposed to MCP. For example in case of port forwarding:

```sh
kubectl port-forward pod/timebase-consolidated-0 8011:8011 8021:8021 -n dev-namespace
```


# See also

[TimeBase Agent Plugins](https://github.com/epam/TimeBase-Agent-Plugins/)
