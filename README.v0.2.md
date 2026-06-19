# TimeBase MCP

A [Model Context Protocol](https://modelcontextprotocol.io/introduction) server that lets an agent (Claude Code, VS Code, Cursor, Claude Desktop, etc.) explore and query [TimeBase](https://kb.timebase.info): list streams, read schemas and symbols, preview messages, and run QQL queries.

The server can run two ways:

- **Locally** — your agent launches `timebase-mcp` as a local process (`stdio`) that connects to your TimeBase.
- **Remotely** — you deploy `timebase-mcp` as a shared HTTP service that multiple users connect their agents to.

## Which guide do I need?

| You want to | Go to |
| - | - |
| Use MCP on your local machine | [Local setup](#local-setup) |
| Set up a shared TimeBase MCP server for your team | [Remote deployment](#remote-deployment) |
| Connect to a running remote TimeBase MCP server | [Connect to a remote server](#connect-to-a-remote-server) |

For a full list of settings and behaviors, see the [Reference](#reference).

---

## Installation

> [!NOTE]
> You only need to install `timebase-mcp` for **local setup** or to **deploy a remote server**. If you are just connecting your agent to a running remote server, skip to [Connect to a remote server](#connect-to-a-remote-server).

**Prerequisites:** Python 3.10–3.14 and one of [pip](https://pip.pypa.io/en/stable/installation/), [uv](https://docs.astral.sh/uv/getting-started/installation/), or [pipx](https://pipx.pypa.io/stable/how-to/install-pipx/).

<!--TODO: Remove pre-release flags when v0.2 is released.-->
| Tool | Command |
| - | - |
| **uv (recommended)** | `uv tool install -p 3.14 --prerelease allow --from "timebase-mcp[all]" timebase-mcp` |
| **pip** | `python -m pip install --pre "timebase-mcp[all]"` |
| **pipx** | `pipx install --pip-args="--pre" --python 3.14 "timebase-mcp[all]"` |

The `[all]` extra installs both TimeBase client editions; the server picks the right one per connected instance.

> [!WARNING]
> With **pip**, do not install into a manually created virtual environment — the `timebase-mcp` command must be globally on `PATH` so your MCP client can launch it. Use **pipx** or **uv** if you want isolation (they handle `PATH` automatically). If pip reports an externally-managed environment, use uv or pipx instead.

**Verify** the install (from a new terminal, so `PATH` is fresh):

```bash
timebase-mcp -v
```

## Updating

| Tool | Command |
| - | - |
| **uv** | `uv tool upgrade -p 3.14 timebase-mcp` |
| **pipx** | `pipx upgrade --python 3.14 timebase-mcp` |
| **pip** | `python -m pip install --upgrade "timebase-mcp[all]"` |

Run `timebase-mcp -v` to confirm the new version.

---

## Local setup

For when you run TimeBase MCP on your own machine and your agent launches it over `stdio`.

### 1. Install

Follow [Installation](#installation) instructions.

### 2. Choose how MCP connects to TimeBase

Set these as environment variables in your MCP client config (next step). Pick the row that matches your TimeBase:

| Your TimeBase | Set | Outbound mode |
| - | - | - |
| Unprotected | `TIMEBASE_URL` only | `none` |
| Username / password | `TIMEBASE_URL`, `TIMEBASE_USERNAME`, `TIMEBASE_PASSWORD` | `basic` |
| Protected by an IdP (OAuth) | `TIMEBASE_URL` | `interactive` |

With no explicit `TIMEBASE_AUTH_MODE`, the server uses `auto`: it connects anonymously to an unprotected server, and falls back to an interactive browser login when TimeBase advertises OAuth. See [Auto mode decision order](#auto-mode-decision-order).

#### Interactive redirect URI

Interactive (browser) login is only available for local **stdio** MCP. It opens your IdP's login page in the browser, then MCP captures the result on a **loopback redirect URI**. For stdio, `MCP_HOST` and `MCP_PORT` control this redirect only — they do not start an HTTP MCP server.

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
> MCP binds a short-lived loopback listener on that port during login. If TimeBase Desktop Admin is running and already holds the port, close Admin first or use Option A with a different port.

### 3. Add the server to your MCP client

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

### 4. Verify

Restart/reload your client and ask the agent to list TimeBase streams. If something fails, see [Troubleshooting](#troubleshooting).

---

## Remote deployment

Use this when one `timebase-mcp` HTTP server is shared by multiple users. There are two separate auth directions:

- **Inbound** protects the MCP HTTP endpoint from callers.
- **Outbound** controls how `timebase-mcp` connects to TimeBase.

### OAuth

`timebase-mcp` is an **OAuth Resource Server** only. It validates bearer tokens and can publish OAuth Protected Resource Metadata for MCP clients. It does **not** issue tokens or host login pages. Your IdP is the **Authorization Server**.

> [!WARNING]
> **Microsoft Entra ID:** inbound SSO for remote HTTP MCP is **not supported** today. Remote MCP clients send RFC 8707 `resource=<MCP URL>` from Protected Resource Metadata. Since March 2026 Entra v2.0 rejects that against `api://...` scopes (`AADSTS9010010`). For Entra-backed teams, use **API keys** for remote MCP access, **local `stdio`** for user OAuth to TimeBase, or **another IdP**. See [AADSTS9010010 (Microsoft Entra ID)](#aadsts9010010-microsoft-entra-id).

### 1. Choose a deployment pattern

| Pattern | Inbound MCP auth | Outbound TimeBase auth | Use when | Key settings |
| - | - | - | - | - |
| **Per-user SSO** | JWT from your IdP | `forward_identity` — forward the caller's token to TimeBase | TimeBase should enforce each user's own permissions | `MCP_AUTH_PUBLIC_URL`, `MCP_AUTH_AUDIENCE=<TimeBase API audience>`; issuer/JWKS from TimeBase |
| **SSO + service account** | JWT from your IdP | `oauth2_client_credentials` — one MCP service identity connects to TimeBase | Callers authenticate to MCP, but TimeBase sees a shared service account | `MCP_AUTH_PUBLIC_URL`, `MCP_AUTH_AUDIENCE=<MCP API audience>`, `MCP_AUTH_ISSUER_URL`, `MCP_AUTH_REQUIRED_SCOPES`, `TIMEBASE_OAUTH2_*` |
| **API keys** | Static bearer keys generated by `timebase-mcp keys` | `none`, `basic`, or service-account OAuth | No browser SSO, CI, private automation | `MCP_AUTH_API_KEYS_FILE`; no `MCP_AUTH_AUDIENCE` or `MCP_AUTH_PUBLIC_URL` needed |
| **Auth at a proxy/gateway** | Reverse proxy enforces auth before traffic reaches MCP | Any non-`forward_identity` mode | Enterprise gateway already handles auth | Omit `MCP_AUTH_AUDIENCE` and `MCP_AUTH_API_KEYS_FILE`; ensure the proxy is the only reachable entry point |

On HTTP transports, inbound auth is enabled when you set `MCP_AUTH_AUDIENCE` (IdP) or `MCP_AUTH_API_KEYS_FILE` (API keys).

### 2. Configure the HTTP endpoint

Set the HTTP transport and bind address:

```dotenv
MCP_TRANSPORT=streamable-http
MCP_HOST=0.0.0.0
MCP_PORT=8000
```

Terminate TLS at a reverse proxy / load balancer and expose the MCP endpoint over HTTPS. With the default streamable-HTTP path, clients connect to:

```text
https://mcp.example.com/mcp
```

If you use IdP inbound auth, set `MCP_AUTH_PUBLIC_URL` to that same external MCP endpoint URL:

```dotenv
MCP_AUTH_PUBLIC_URL=https://mcp.example.com/mcp
```

### 3. Configure inbound auth

Choose one inbound mode.

#### IdP

```dotenv
MCP_AUTH_PUBLIC_URL=https://mcp.example.com/mcp
MCP_AUTH_AUDIENCE=api://timebase-api
# Required when TimeBase has no OAuth or uses a separate MCP API audience:
# MCP_AUTH_ISSUER_URL=https://login.example.com/realms/myrealm
# MCP_AUTH_JWKS_URL=https://login.example.com/realms/myrealm/protocol/openid-connect/certs
# MCP_AUTH_REQUIRED_SCOPES=timebase.read
```

JWT tokens are validated for signature, expiry, issuer, audience (`MCP_AUTH_AUDIENCE`), and required scopes (`MCP_AUTH_REQUIRED_SCOPES`, if set). The current verifier accepts RS256-signed JWTs.

#### API keys

API keys are bearer tokens stored as a hashed JSON key store; the server only reads hashes and verifies against them. Each key has a name and optional scopes, so every key is a distinct caller (gated by `MCP_AUTH_REQUIRED_SCOPES`).

Generate and manage keys with the `timebase-mcp keys` CLI, then make the updated hashed store available at `MCP_AUTH_API_KEYS_FILE` (for example by updating a Vault entry or mounted volume). The `generate` command prints the plaintext key once, and editing the store in-place requires write access to a file.

```bash
# Generate a key, it prints the plaintext key once,
# and writes only its hash to the store:
timebase-mcp keys generate --name user --scopes timebase.read --file keys.json

timebase-mcp keys list --file keys.json
timebase-mcp keys revoke user --file keys.json
```

For Kubernetes/secret managers, use `--stdout` to emit the hashed record (no file write) and pipe it into your Secret/Vault:

```bash
timebase-mcp keys generate --name ci-bot --scopes timebase.read --stdout
```

Mount the store as a **Secret/ConfigMap** (k8s) or volume (Docker) at `MCP_AUTH_API_KEYS_FILE`. The server re-reads it when it changes, so adding or revoking keys takes effect without a restart.

### 4. Set up your IdP for OAuth clients

For IdP mode, register the OAuth pieces in your IdP. Remember: the IdP is the Authorization Server; `timebase-mcp` is only a Resource Server.

1. **An API / resource (audience)** whose identifier becomes `MCP_AUTH_AUDIENCE`.
   - For **per-user SSO / `forward_identity`**, use the TimeBase API audience because the same token is forwarded to TimeBase.
   - For **SSO + service account**, this can be a separate MCP API audience because MCP does not forward the caller's token to TimeBase.
2. **A client application** that end users' MCP clients authenticate through, with appropriate redirect URIs and scopes.
3. **TimeBase UAC validation** if TimeBase should accept the same user tokens. Configure TimeBase with the IdP issuer and JWKS (see the [TimeBase UAC OAuth2 guide](https://kb.timebase.info/docs/development/tools/uac#oauth2)).

Whether end users need a client ID depends on IdP support for Dynamic Client Registration:

| IdP capability | What happens | End user provides |
| - | - | - |
| **Supports DCR** (e.g. Keycloak, Auth0) | MCP clients self-register with the IdP, users just log in | Usually nothing beyond the server URL |
| **No DCR** (e.g. Azure Entra ID) | You must pre-register a client app | A client ID, plus a registered redirect URI / callback port |

For IdPs with no DCR, register a backend API app (exposing a scope, e.g. `api://timebase/mcp`) and a client app (with redirect URIs and the API permission). Distribute the client ID to your users for the [Connect to a remote server](#connect-to-a-remote-server) step.

For **TimeBase-side OAuth** (local `interactive` login or outbound service accounts), see the [TimeBase UAC OAuth2 guide](https://kb.timebase.info/docs/development/tools/uac#oauth2) and the [TimeBase Entra ID registration howto](https://kb.timebase.info/docs/development/howto#azure-ad-entra-id-application-registration-for-timebase-applications).

### 5. Configure outbound auth to TimeBase

Set `TIMEBASE_AUTH_MODE` (or leave it `auto`):

| Mode | What it does | Settings |
| - | - | - |
| `forward_identity` | Forwards each authenticated caller's bearer token to TimeBase, so TimeBase enforces that user's permissions | Requires inbound JWT auth + HTTP transport; TimeBase must advertise OAuth |
| `oauth2_client_credentials` | MCP connects with one shared service-account | `TIMEBASE_OAUTH2_TOKEN_URL`, `TIMEBASE_OAUTH2_CLIENT_ID`, `TIMEBASE_OAUTH2_CLIENT_SECRET`, `TIMEBASE_OAUTH2_SCOPE` |
| `basic` | One shared username/password | `TIMEBASE_USERNAME`, `TIMEBASE_PASSWORD` |
| `none` | — | — |

> [!IMPORTANT]
> **`forward_identity` audience requirement.** The caller's token is forwarded to TimeBase **as-is**. For both MCP and TimeBase to accept it, the token's `aud` must be valid for TimeBase and must match `MCP_AUTH_AUDIENCE`. `MCP_AUTH_PUBLIC_URL` remains the MCP endpoint URL, do not set it to the IdP URL or TimeBase URL. If you need separate audiences for MCP and TimeBase, use `oauth2_client_credentials` instead.

### 6. Remote operation limits

Shared remote servers should limit concurrent TimeBase operations so one busy agent session cannot exhaust the server. These settings apply globally across all callers.

| Variable | Default | What it does |
| - | - | - |
| `MCP_MAX_CONCURRENT_OPS` | `0` (unlimited) | Max concurrent TimeBase operations in flight. When the limit is reached, new tool calls fail with a backpressure error. |
| `MCP_OPERATION_TIMEOUT_SECONDS` | `0` (disabled) | Per-operation deadline in seconds. |

Example configuration (tune to your TimeBase capacity):

```dotenv
MCP_MAX_CONCURRENT_OPS=10
MCP_OPERATION_TIMEOUT_SECONDS=60
```

### 7. Run the server

<details open>
<summary>Docker (recommended)</summary>

The image is available from GitHub Container Registry as `ghcr.io/epam/timebase-mcp`. The [`Dockerfile`](Dockerfile) installs `timebase-mcp[all]`, so the server auto-selects the right client edition per connected TimeBase instance. Defaults: `MCP_TRANSPORT=streamable-http`, `MCP_HOST=0.0.0.0`, `MCP_PORT=8000`.

Create an env file from one of the examples below, then run:

```bash
docker run --rm -p 8000:8000 \
  --env-file ./timebase-mcp.env \
  ghcr.io/epam/timebase-mcp:latest
```

</details>

<details>
<summary>From an installed package</summary>

Install per [Installation](#installation), export the env vars from one of the examples below, then run:

```bash
timebase-mcp
```

</details>

### Example deployments

**Per-user SSO:**

```dotenv
MCP_TRANSPORT=streamable-http
MCP_HOST=0.0.0.0
MCP_PORT=8000
MCP_AUTH_PUBLIC_URL=https://mcp.example.com/mcp
MCP_AUTH_AUDIENCE=api://timebase-api
# If /tb/oauthinfo is empty or unreachable, set explicitly:
# MCP_AUTH_ISSUER_URL=https://login.example.com/realms/myrealm
# MCP_AUTH_JWKS_URL=https://login.example.com/realms/myrealm/protocol/openid-connect/certs

TIMEBASE_URL=dxtick://prod:8011
# Optional, default `auto` will discover OAuth from TimeBase and use `forward_identity`
# TIMEBASE_AUTH_MODE=forward_identity

MCP_MAX_CONCURRENT_OPS=10
MCP_OPERATION_TIMEOUT_SECONDS=60
```

**SSO for MCP, unprotected TimeBase:**

Inbound SSO protects MCP, TimeBase has no auth. `MCP_AUTH_ISSUER_URL` is required, because `/tb/oauthinfo` does not provide an issuer. Register a separate MCP API app in your IdP (`MCP_AUTH_AUDIENCE`) and expose the scope used in `MCP_AUTH_REQUIRED_SCOPES`.

```dotenv
MCP_TRANSPORT=streamable-http
MCP_HOST=0.0.0.0
MCP_PORT=8000
MCP_AUTH_PUBLIC_URL=https://mcp.example.com/mcp
MCP_AUTH_AUDIENCE=api://mcp-api
MCP_AUTH_ISSUER_URL=https://login.example.com/realms/myrealm
# Optional if OIDC metadata exposes jwks_uri:
# MCP_AUTH_JWKS_URL=https://login.example.com/realms/myrealm/protocol/openid-connect/certs
MCP_AUTH_REQUIRED_SCOPES=example.mcp.access

TIMEBASE_URL=dxtick://prod:8011
TIMEBASE_AUTH_MODE=none

MCP_MAX_CONCURRENT_OPS=10
MCP_OPERATION_TIMEOUT_SECONDS=60
```

**SSO for MCP, protected TimeBase:**

Same inbound MCP SSO setup as above, but MCP connects to TimeBase with a shared service account.

```dotenv
MCP_TRANSPORT=streamable-http
MCP_HOST=0.0.0.0
MCP_PORT=8000
MCP_AUTH_PUBLIC_URL=https://mcp.example.com/mcp
MCP_AUTH_AUDIENCE=api://mcp-api
MCP_AUTH_ISSUER_URL=https://login.example.com/realms/myrealm
MCP_AUTH_REQUIRED_SCOPES=example.mcp.access

TIMEBASE_URL=dxtick://prod:8011
TIMEBASE_OAUTH2_CLIENT_ID=<service-client-id>
TIMEBASE_OAUTH2_CLIENT_SECRET=<service-client-secret>
# Optional, default `auto` will infer `oauth2_client_credentials` from `TIMEBASE_OAUTH2_*` vars
# TIMEBASE_AUTH_MODE=oauth2_client_credentials
# Optional, discovered from TimeBase when possible:
# TIMEBASE_OAUTH2_TOKEN_URL=https://login.example.com/oauth2/token
# TIMEBASE_OAUTH2_SCOPE=api://timebase-api/.default

MCP_MAX_CONCURRENT_OPS=10
MCP_OPERATION_TIMEOUT_SECONDS=60
```

Use `TIMEBASE_OAUTH2_TOKEN_PARAMS` (a JSON object) only if your provider needs extra token fields such as `audience` or `resource`; it cannot override `grant_type`, `client_id`, `client_secret`, or `scope`.

**Protect MCP with API keys, unprotected TimeBase:**

```dotenv
MCP_TRANSPORT=streamable-http
MCP_HOST=0.0.0.0
MCP_PORT=8000
MCP_AUTH_API_KEYS_FILE=/etc/timebase-mcp/keys.json
# Optional, per-key scopes are checked against it:
# MCP_AUTH_REQUIRED_SCOPES=timebase.read

TIMEBASE_URL=dxtick://tb:8011
# Optional, default `auto` will connect without auth if TimeBase is unprotected
# TIMEBASE_AUTH_MODE=none

MCP_MAX_CONCURRENT_OPS=10
MCP_OPERATION_TIMEOUT_SECONDS=60
```

### TLS / SSL to TimeBase

Connections to TimeBase may need extra SSL variables handled by `dxapi`:

- `DXAPI_SSL_TERMINATION=true` — TimeBase is behind an HTTPS/TLS terminator.
- `DXAPI_SSL_CERT_FILE=/path/to/cert.der` — trust a private/self-signed certificate.
- `DXAPI_SSL_TRUST_ALL=true` — disable certificate verification, this also disables verification for OAuth discovery fetches.

See [dxapi environment variables](https://kb.timebase.info/docs/development/clients/python%20dxapi/python_dxapi_configuration#environment-variables) and [SSL configuration](https://kb.timebase.info/docs/development/clients/python%20dxapi/python_dxapi_configuration#ssl-configuration).

---

## Connect to a remote server

For connecting to an already running `timebase-mcp` HTTP server. You do **not** install `timebase-mcp` yourself.

### What you need from the server admin

- The **server URL** (e.g. `https://mcp.example.com/mcp`).
- **Which inbound auth** the server uses:
  - **API key** — the operator gives you a key (`tbk_...`); see [Client configuration examples](#api-key) on how to use it.
  - **OAuth (IdP)** — you sign in via your browser. Also confirm whether the IdP **supports DCR**; if **not** (e.g. Azure Entra ID) you need an OAuth **client ID**, the **scopes**, and the **redirect URI / callback port** registered for your client (see [OAuth redirect URIs](#oauth-redirect-uris)).

### OAuth redirect URIs

If your IdP does not support Dynamic Client Registration, register these redirect URIs:

| MCP client | Redirect URI to register |
| - | - |
| **Cursor** | `cursor://anysphere.cursor-mcp/oauth/callback` |
| **VS Code** | `http://127.0.0.1:33418` and `https://vscode.dev/redirect`; or use **Accounts: Manage Trusted MCP Servers for Account** for Entra or GitHub |
| **Claude Code** | `http://localhost:<callback-port>/callback` (port must match `--callback-port`) |

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

---

## Reference

### Environment variables

| Variable | Default | Description |
| - | - | - |
| `TIMEBASE_URL` | `dxtick://localhost:8011` | TimeBase native connection URL. |
| `TIMEBASE_SERVERS` | None | Multi-server list: a JSON array string, a path to a JSON file, or omit and use indexed `TIMEBASE_SERVERS_{n}_*` env vars (see [Multi-server configuration](#multi-server-timebase-configuration)). |
| `TIMEBASE_USERNAME` | None | Username for `basic` auth; optional username override for `oauth2_client_credentials`. |
| `TIMEBASE_PASSWORD` | None | Password for `basic` auth. |
| `TIMEBASE_AUTH_MODE` | `auto` | Outbound mode: `auto`, `none`, `basic`, `oauth2_client_credentials`, `forward_identity`, `interactive`. |
| `TIMEBASE_HTTP_URL` | derived | TimeBase HTTP base URL for OAuth discovery. MCP derives this from `TIMEBASE_URL` when unset. **Enterprise 5.6 and earlier** serve HTTP on the same port as native (typically `8011`). **Community Edition and Enterprise 5.7** use a separate HTTP port by default (typically `8021`), set `TIMEBASE_HTTP_URL` explicitly for those versions. |
| `TIMEBASE_OAUTH2_TOKEN_URL` | None | Token endpoint for outbound service-account client credentials. |
| `TIMEBASE_OAUTH2_CLIENT_ID` | None / discovered | OAuth2 client ID for service-account auth, or a dedicated client-app override for local `interactive` login. |
| `TIMEBASE_OAUTH2_CLIENT_SECRET` | None | OAuth2 client secret for service-account auth. |
| `TIMEBASE_OAUTH2_SCOPE` | discovered / None | OAuth2 scope(s). For service accounts set the provider-required value; for local `interactive`, this may override the discovered login scopes. |
| `TIMEBASE_OAUTH2_TOKEN_PARAMS` | None | JSON object of extra client-credentials token form params. Cannot override reserved fields. |
| `MCP_TRANSPORT` | `stdio` | Transport: `stdio` or `streamable-http`. |
| `MCP_HOST` | `127.0.0.1` | HTTP bind host. For stdio, also the loopback host used for interactive OAuth redirect (`http://MCP_HOST:MCP_PORT/`). |
| `MCP_PORT` | `8000` | HTTP bind port (1–65535). For stdio, also the loopback port used for interactive OAuth redirect. |
| `MCP_MAX_CONCURRENT_OPS` | `0` | Max concurrent TimeBase operations (`0` disables limits). |
| `MCP_OPERATION_TIMEOUT_SECONDS` | `0` | Per-operation timeout in seconds (`0` disables). |
| `MCP_AUTH_ISSUER_URL` | discovered | IdP mode: issuer override. Required when TimeBase `/tb/oauthinfo` is empty or for a separate MCP API audience. |
| `MCP_AUTH_JWKS_URL` | discovered | IdP mode: JWKS URL override. If unset, discovered from `/tb/oauthinfo`. |
| `MCP_AUTH_AUDIENCE` | None | IdP mode: expected JWT audience/resource. **Required** for IdP inbound auth. |
| `MCP_AUTH_REQUIRED_SCOPES` | None | Scopes required on inbound tokens. |
| `MCP_AUTH_PUBLIC_URL` | None | IdP mode: public URL of this MCP Resource Server. Required as a public endpoint for non-loopback HTTP binds. |
| `MCP_AUTH_API_KEYS_FILE` | None | Path to a hashed API-key store |
| `MCP_LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, or `CRITICAL`. |

`dxapi` SSL variables (`DXAPI_SSL_TERMINATION`, `DXAPI_SSL_TRUST_ALL`, `DXAPI_SSL_CERT_FILE`) are read by the TimeBase client library, see [TLS / SSL to TimeBase](#tls--ssl-to-timebase).

#### Multi-server TimeBase configuration

Connect one `timebase-mcp` process to multiple TimeBase servers. The server exposes `list_timebase_instances` tool; agents call it and pass the relevant instance key to the tool calls. When a tool omits the instance key, the first configured server is used.

| Where you configure | How |
| - | - |
| Remote / Docker | `TIMEBASE_SERVERS=/path/to/servers.json` |
| Local MCP client (hand-edited) | Indexed env vars: `TIMEBASE_SERVERS_0_URL`, `_0_NAME`, ... |
| Local MCP client (rich config) | Edit a JSON file -> `timebase-mcp servers-print file.json` -> paste into `TIMEBASE_SERVERS` |

Per-server OAuth stays in **JSON or file** only. Indexed env supports URL, name, description, and basic auth (`username` / `password`).

**File**

```dotenv
TIMEBASE_SERVERS=/etc/timebase-mcp/servers.json
```

Mount [`examples/timebase-servers.json`](examples/timebase-servers.json) or your own file at that path.

**Indexed env**:

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
| `TIMEBASE_SERVERS_{n}_URL` | `url` (required; scan stops when missing) |
| `TIMEBASE_SERVERS_{n}_NAME` | `name` |
| `TIMEBASE_SERVERS_{n}_DESCRIPTION` | `description` |
| `TIMEBASE_SERVERS_{n}_USERNAME` | `username` |
| `TIMEBASE_SERVERS_{n}_PASSWORD` | `password` |

**JSON string:**

```bash
timebase-mcp servers-print examples/timebase-servers.json
```

Paste the output as the `TIMEBASE_SERVERS` value in `mcp.json`:

```json
"TIMEBASE_SERVERS": "[{\"name\":\"enterprise\",\"description\":\"Enterprise TimeBase\",\"url\":\"dxtick://localhost:8011\",...}]"
```

### Authentication model

There are two independent directions:

- **Inbound** — protects the MCP HTTP endpoint from MCP clients. Only meaningful for `streamable-http`; local `stdio` has no inbound request to authenticate. Enabled when `MCP_AUTH_AUDIENCE` or `MCP_AUTH_API_KEYS_FILE` is set.
- **Outbound** — controls how MCP connects to TimeBase.

#### Auto mode decision order

`auto` (the default) resolves the outbound mode at first connection:

1. If username/password are configured -> `basic`.
2. Else if OAuth2 client credentials are configured -> `oauth2_client_credentials`.
3. Else probe TimeBase OAuth metadata via HTTP `/tb/oauthinfo` endpoint.
4. If TimeBase advertises OAuth and MCP runs remote HTTP with IdP/JWT inbound auth -> `forward_identity`.
5. Else if TimeBase advertises OAuth and MCP uses stdio transport -> `interactive`.
6. Else -> `none`.

### Tools

| Name | Description | Key inputs |
| - | - | - |
| `list_timebase_instances` | List configured TimeBase instances and descriptions | None |
| `list_streams` | List available TimeBase streams with descriptions | optional `instance_key` |
| `get_stream_schema` | Get the schema of a specific stream | `stream_key`, optional `instance_key` |
| `get_stream_time_range` | Get the UTC time range of a stream | `stream_key`, optional `instance_key` |
| `get_stream_symbols` | Get symbols from a stream (sorted, paginated) | `stream_key`, optional `instance_key`, `limit` (1–500), `cursor` |
| `get_stream_messages` | Preview first/last messages from a stream | `stream_key`, optional `instance_key`, `reverse`, `count` |
| `execute_query` | Execute a TimeBase QQL query (limited preview) | `query`, optional `instance_key`, `limit` (1–100) |
| `compile_query` | Compile a QQL query (parser-level diagnostics only) | `query`, optional `instance_key` |

### Resources

Some clients (e.g. VS Code) let you add resources to the context explicitly.

| URI | Name | Description |
| - | - | - |
| `timebase://streams` | `stream_catalog` | Text resource listing streams and descriptions |
| `timebase://streams/{stream_key}/schema` | `stream_schema` | Resource template exposing a stream schema by key |

---

## Troubleshooting

### Finding logs

<details>
<summary>VS Code</summary>

Logs can be found in the output panel (`View > Output`, then select timebase-mcp from the dropdown).

</details>

<details>
<summary>Cursor</summary>

Logs can be found in the Cursor's output panel.

#### In the Editor window:

Open via `View > Output`, then select `timebase-mcp` from the dropdown.

#### In the Agent window:

From the command palette (`Ctrl+Shift+P` or `Cmd+Shift+P`), run `New Output View` and select `timebase-mcp` as the output channel.

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

- **Connection refused** (`Connection refused at SOCKET`): TimeBase isn't running or isn't reachable (wrong URL, firewall, WSL/network). Port layout depends on TimeBase version:
  - **Enterprise 5.6 and earlier:** native and HTTP usually share one port (typically `8011`).
  - **Community Edition and Enterprise 5.7:** native (usually `8011`) and HTTP (usually `8021`) are separate, forward or expose both, e.g.:

  ```sh
  kubectl port-forward pod/timebase-consolidated-0 8011:8011 8021:8021 -n dev-namespace
  ```

- **Edition mismatch:** connecting to Enterprise with only the community client installed (or vice versa) surfaces protocol-version errors. Reinstall with `[all]`.

- **Remote access not enabled:** some features require remote access on the TimeBase server, see the [Enterprise](https://kb.timebase.info/docs/deployment/config#system-remoteMonitoring) / [Community](https://kb.timebase.info/community/deployment/config#system-remoteMonitoring) docs.

- **Timeout connecting:** TimeBase may be behind a TLS terminator. Set `DXAPI_SSL_TERMINATION=true`.

- **TLS/SSL certificate error:** set `DXAPI_SSL_CERT_FILE=/path/to/cert.der`, or `DXAPI_SSL_TRUST_ALL=true` for non-production testing only.

### Authentication issues

- **`Wrong username or password` with URL-only config:** the server is protected but MCP connected anonymously. Locally, keep `TIMEBASE_AUTH_MODE` unset (auto) or set `interactive`. Remotely, use `forward_identity` or a service account.

- **OAuth discovery fails for `/tb/oauthinfo`:** On **Enterprise 5.6 and earlier**, HTTP is usually on the same port as `TIMEBASE_URL`, explicit `TIMEBASE_HTTP_URL` is unnecessary. On **CE / Enterprise 5.7**, set `TIMEBASE_HTTP_URL` to the HTTP base (typically `https://host:8021`).

- **Redirect URI mismatch during interactive login:** the browser shows a redirect error from your IdP. MCP sent a `redirect_uri` that is not registered on the OAuth client. Fix it:
  1. Find `OAuth callback URI` in the MCP logs.
  2. Compare it to the redirect URIs registered on the OAuth client in your IdP.
  3. Register MCP's URI on the client, or set `MCP_HOST`/`MCP_PORT` to match an existing registration (e.g. TimeBase Desktop Admin).
  4. Match host (`localhost` vs `127.0.0.1`), port, path, and trailing slash exactly; ensure the port is free when MCP logs in.

- **Remote clients can't authenticate / "does not support dynamic client registration":** your IdP has no DCR. Pre-register a client app and have users supply the client ID, see [Connect to a remote server](#connect-to-a-remote-server).

- **All API keys rejected (401):** the key store is missing, unreadable, or invalid JSON. Check `MCP_AUTH_API_KEYS_FILE` and that the mounted store parses (`timebase-mcp keys list --file ...`). Keys are matched by hash, so a key works only if its hashed record is present.

- **401 after successful browser login (JWT inbound):** token `aud` does not match `MCP_AUTH_AUDIENCE`. For `forward_identity`, set `MCP_AUTH_AUDIENCE` to the TimeBase API Application ID URI, not the MCP URL.

- **Wrong scope in remote client config:** user login needs the delegated API scope your IdP admin configured (e.g. `api://<id>/app` from `/tb/oauthinfo` for `forward_identity`, or the MCP API scope for a separate MCP audience).

#### AADSTS9010010 (Microsoft Entra ID)

**Symptom:** `AADSTS9010010: The resource parameter doesn't match the requested scopes` during remote MCP client OAuth (Cursor, VS Code, Claude Code).

**Cause:** Remote MCP clients fetch [OAuth Protected Resource Metadata](https://datatracker.ietf.org/doc/html/rfc9728) from your server and send RFC 8707 `resource=<MCP HTTPS URL>` to Entra together with `api://...` scopes. From March 2026 Entra v2.0 rejects that combination. This affects all remote Entra inbound SSO. See [MCP Python SDK #2578](https://github.com/modelcontextprotocol/python-sdk/issues/2578).

**Workarounds:**

- **API-key inbound auth** for remote MCP access.
- **Local `stdio` + `interactive`** for user OAuth login to TimeBase.
- **Another IdP** that supports the MCP remote OAuth flow for inbound JWT auth.
- **Gateway/proxy auth** in front of MCP.

### Operation limit issues

- **`Maximum concurrent TimeBase operations reached`:** raise `MCP_MAX_CONCURRENT_OPS` or reduce parallel agent activity. This is intentional backpressure when the global limit is saturated.
- **Operations timing out:** increase `MCP_OPERATION_TIMEOUT_SECONDS` for slow queries, or narrow QQL in the agent. Check TimeBase load and network latency.

---

## See also

- [TimeBase Agent Plugins](https://github.com/epam/TimeBase-Agent-Plugins)
