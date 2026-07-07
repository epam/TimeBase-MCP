# Connect to a remote server

For connecting to an already running `timebase-mcp` HTTP server. You do **not** install `timebase-mcp` yourself.

## 1. What you need from the server admin

- The **server URL** (e.g. `https://mcp.example.com/mcp`).
- **Which inbound auth** the server uses:
  - **API key** — the operator gives you a key (`tbk_...`); configure in [step 3](#3-configure-your-client).
  - **OAuth (IdP)** — you sign in via your browser. Also confirm whether the IdP **supports DCR**; if **not** (e.g. Azure Entra ID) you need an OAuth **client ID**, the **scopes**, and the **redirect URI / callback port** registered for your client (see [step 2](#2-oauth-redirect-uris)).

## 2. OAuth redirect URIs

Skip to [step 3](#3-configure-your-client) if your server uses API keys.

If your IdP does not support Dynamic Client Registration, register these redirect URIs:

| MCP client | Redirect URI to register |
| - | - |
| **Cursor** | `cursor://anysphere.cursor-mcp/oauth/callback` |
| **VS Code** | `http://127.0.0.1:33418` and `https://vscode.dev/redirect`; or use **Accounts: Manage Trusted MCP Servers for Account** for Entra or GitHub |
| **Claude Code** | `http://localhost:<callback-port>/callback` (port must match `--callback-port`) |

## 3. Configure your client

Pick the section that matches your server's inbound auth, then your MCP client.

### API key

Send the key as a bearer header:

<details>
<summary>Claude Code</summary>

```bash
claude mcp add --transport http timebase-mcp https://mcp.example.com/mcp \
  --header "Authorization: Bearer ${TB_MCP_API_KEY}"
```
</details>

<details>
<summary>Cursor</summary>

```json
{
  "mcpServers": {
    "timebase": {
      "url": "https://mcp.example.com/mcp",
      "headers": {
        "Authorization": "Bearer ${env:TB_MCP_API_KEY}"
      }
    }
  }
}
```

</details>

<details>
<summary>VS Code</summary>

```json
{
  "servers": {
    "timebase": {
      "type": "http",
      "url": "https://mcp.example.com/mcp",
      "headers": {
        "Authorization": "Bearer ${env:TB_MCP_API_KEY}"
      }
    }
  }
}
```

</details>

### OAuth

<details>
<summary>Claude Code</summary>

Add the server, then authenticate in your browser with `/mcp`:

```bash
claude mcp add --transport http timebase-mcp https://mcp.example.com/mcp
```

```text
/mcp
```

If the IdP does **not** support DCR, pass pre-registered credentials (`--callback-port` must match the redirect URI `http://localhost:PORT/callback` registered for your client):

```bash
claude mcp add --transport http \
  --client-id <your-oauth-client-id> --callback-port 8080 \
  timebase-mcp https://mcp.example.com/mcp
```

Register `http://localhost:8080/callback` in the IdP settings.

</details>

<details>
<summary>VS Code</summary>

Add the server to `.vscode/mcp.json`:

```json
{
  "servers": {
    "timebase-mcp": {
      "type": "http",
      "url": "https://mcp.example.com/mcp"
    }
  }
}
```

VS Code attempts DCR first and falls back to a manual **Client ID** prompt when the IdP doesn't support it. For **Microsoft Entra ID** or **GitHub**, use **Accounts: Manage Trusted MCP Servers for account** to sign in, or add a client ID when prompted after the first connection attempt.

For auth without DCR, register `http://127.0.0.1:33418` and `https://vscode.dev/redirect` in your IdP settings.

</details>

<details>
<summary>Cursor</summary>

Cursor uses static OAuth, when DCR is unavailable: supply the client ID the IdP admin gives you.

```json
{
  "mcpServers": {
    "timebase-mcp": {
      "url": "https://mcp.example.com/mcp",
      "auth": {
        "CLIENT_ID": "your-oauth-client-id",
        "scopes": ["api://<timebase-api-id>/app"]
      }
    }
  }
}
```

`CLIENT_SECRET` is optional for public client flows; `scopes` can be omitted if discovered from authorization-server metadata.

</details>

## 4. Verify

Restart/reload your client and ask the agent to list TimeBase streams. If something fails, see [Troubleshooting](troubleshooting.md).
