# Troubleshooting

## Finding logs

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

## Windows setup issues

- **`timebase-mcp` is not recognized / MCP client cannot find the command:** with `pip`, Windows may install console scripts into a Python `Scripts` directory that is not on your user `PATH` by default. Verify from a new PowerShell and, if needed, search the common Windows Python install roots:

  ```powershell
  timebase-mcp -v
  Get-ChildItem -Path "$env:LOCALAPPDATA\Python", "$env:APPDATA\Python" -Filter timebase-mcp.exe -Recurse -ErrorAction SilentlyContinue
  ```

  If the first command fails, add the actual directory containing `timebase-mcp.exe` to your user `PATH` or use the absolute `.exe` path in your MCP client config. `uv` and `pipx` are usually easier on Windows because they manage command shims and `PATH` more predictably.

  ```json
  {
    "mcpServers": {
      "timebase-mcp": {
        "type": "stdio",
        "command": "C:\\Users\\<you>\\AppData\\Local\\Python\\pythoncore-3.14-64\\Scripts\\timebase-mcp.exe",
        "args": [],
        "env": {
          "TIMEBASE_URL": "dxtick://localhost:8011"
        }
      }
    }
  }
  ```

- **Installed in WSL, client runs on Windows:** local `stdio` MCP runs in the same OS environment as the MCP client. If Cursor, VS Code, or Claude Desktop runs on Windows, it cannot launch a `timebase-mcp` command installed only inside WSL. Install `timebase-mcp` on Windows too, or run both the MCP client and `timebase-mcp` inside WSL / a remote environment.

- **`localhost` points to the wrong place:** `localhost` is resolved from wherever the `timebase-mcp` process runs. If TimeBase runs inside WSL, Docker, or another VM, make sure the native and HTTP TimeBase ports are exposed to the Windows side and set `TIMEBASE_URL` to an address reachable from that environment.

## TimeBase connection issues

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

## Authentication issues

- **`Wrong username or password` with URL-only config:** the server is protected but MCP connected anonymously. Locally, keep `TIMEBASE_AUTH_MODE` unset (auto) or set `interactive`. Remotely, use `forward_identity` or a service account.

- **OAuth discovery fails for `/tb/oauthinfo`:** MCP derives the TimeBase HTTP URL from `TIMEBASE_URL` and, when the native port is `8011`, also tries default HTTP port `8021`. Set `TIMEBASE_HTTP_URL` explicitly for proxies, custom ports, custom paths, or when automatic probing cannot reach the TimeBase HTTP API.

- **Redirect URI mismatch during interactive login:** the browser shows a redirect error from your IdP. MCP sent a `redirect_uri` that is not registered on the OAuth client. Fix it:
  1. Find `OAuth callback URI` in the MCP logs.
  2. Compare it to the redirect URIs registered on the OAuth client in your IdP.
  3. Register MCP's URI on the client, or set `MCP_HOST`/`MCP_PORT` to match an existing registration (e.g. TimeBase Desktop Admin).
  4. Match host (`localhost` vs `127.0.0.1`), port, path, and trailing slash exactly; ensure the port is free when MCP logs in.

- **Remote clients can't authenticate / "does not support dynamic client registration":** your IdP has no DCR. Pre-register a client app and have users supply the client ID, see [Connect to a remote server](connect-remote.md).

- **All API keys rejected (401):** the key store is missing, unreadable, or invalid JSON. Check `MCP_AUTH_API_KEYS_FILE` and that the mounted store parses (`timebase-mcp keys list --file ...`). Keys are matched by hash, so a key works only if its hashed record is present.

- **401 after successful browser login (JWT inbound):** token `aud` does not match `MCP_AUTH_AUDIENCE`. For `forward_identity`, set `MCP_AUTH_AUDIENCE` to the TimeBase API Application ID URI, not the MCP URL.

- **Wrong scope in remote client config:** user login needs the delegated API scope your IdP admin configured (e.g. `api://<id>/app` from `/tb/oauthinfo` for `forward_identity`, or the MCP API scope for a separate MCP audience).

### AADSTS9010010 (Microsoft Entra ID)

**Symptom:** `AADSTS9010010: The resource parameter doesn't match the requested scopes` during remote MCP client OAuth (Cursor, VS Code, Claude Code).

**Cause:** Remote MCP clients fetch [OAuth Protected Resource Metadata](https://datatracker.ietf.org/doc/html/rfc9728) from your server and send RFC 8707 `resource=<MCP HTTPS URL>` to Entra together with `api://...` scopes. From March 2026 Entra v2.0 rejects that combination. This affects all remote Entra inbound SSO. See [MCP Python SDK #2578](https://github.com/modelcontextprotocol/python-sdk/issues/2578).

**Workarounds:**

- **API-key inbound auth** for remote MCP access.
- **Local `stdio` + `interactive`** for user OAuth login to TimeBase.
- **Another IdP** that supports the MCP remote OAuth flow for inbound JWT auth.
- **Gateway/proxy auth** in front of MCP.

## Operation limit issues

- **`Maximum concurrent TimeBase operations reached`:** raise `MCP_MAX_CONCURRENT_OPS` or reduce parallel agent activity. This is intentional backpressure when the global limit is saturated.
- **Operations timing out:** increase `MCP_OPERATION_TIMEOUT_SECONDS` for slow queries, or narrow QQL in the agent. Check TimeBase load and network latency.
