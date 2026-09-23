# Add WebAdmin access

WebAdmin adds optional inspection tools to an existing MCP installation. Native TimeBase tools work without it. Obtain a WebAdmin URL and credentials from the operator. For remote MCP, choose credentials with the [shared WebAdmin identity](reference/webadmin.md#identity-and-availability) in mind.

## 1. Set the WebAdmin URL

Set the base URL reachable from the MCP process:

```dotenv
TIMEBASE_WEBADMIN_URL=https://webadmin.example.com
```

Include a deployment context path if needed. Omit `/api/v0`, embedded credentials, query strings, and fragments. Locally `http://localhost:8099` can be used.

## 2. Choose one credential profile

Use one of the profiles below. Remove settings from any previous WebAdmin profile before switching. Keep native TimeBase and inbound MCP credentials separate. The [environment reference](reference/environment-variables.md#optional-webadmin-connection-and-authentication) lists every setting and combination.

### Built-in password

If WebAdmin reports `BUILT_IN_OAUTH`, set the user credentials. MCP supplies the OAuth client credentials for a standard deployment.

```dotenv
TIMEBASE_WEBADMIN_USERNAME=<username>
TIMEBASE_WEBADMIN_PASSWORD=<password>
```

For a deployment with custom OAuth client credentials, see the [built-in password reference](reference/webadmin.md#built-in-password).

### Basic API key

Use a key name and secret when WebAdmin has basic signed requests enabled and API-key sessions disabled.

```dotenv
TIMEBASE_WEBADMIN_API_KEY=<key-name>
TIMEBASE_WEBADMIN_API_SECRET=<secret>
```

### Session API key

Use a key name and its matching unencrypted RSA PEM private key of at least 2048 bits. Keep the file outside source control and readable by the MCP process.

```dotenv
TIMEBASE_WEBADMIN_API_KEY=<key-name>
TIMEBASE_WEBADMIN_PRIVATE_KEY_FILE=/absolute/path/to/key.pem
```

If WebAdmin uses a different session login path, set `TIMEBASE_WEBADMIN_SESSION_LOGIN_ROOT`. The default is `/session/login`.

### Browser sign-in

Use this profile only with local `stdio`. Obtain a native public-client registration, trusted issuer URL, registered loopback callback, and delegated WebAdmin API scope from the identity provider operator.

```dotenv
TIMEBASE_WEBADMIN_AUTH_MODE=interactive
TIMEBASE_WEBADMIN_CLIENT_ID=<native-client-id>
TIMEBASE_WEBADMIN_ISSUER_URL=https://idp.example.com/issuer
TIMEBASE_WEBADMIN_SCOPE="<approved-api-scopes>"
TIMEBASE_WEBADMIN_REDIRECT_URI=http://localhost:8765/
MCP_OPERATION_TIMEOUT_SECONDS=360
```

Register the exact callback URI and allow the browser login to finish within your MCP client's tool timeout. The callback wait can take up to five minutes. Use a different registered port for each simultaneous instance login.

### Service identity

Use this profile only when WebAdmin accepts the service token and the identity provider supports `client_secret_post`. Obtain the token endpoint, client credentials, and API scope from the operator.

```dotenv
TIMEBASE_WEBADMIN_AUTH_MODE=client_credentials
TIMEBASE_WEBADMIN_TOKEN_URL=https://idp.example.com/token
TIMEBASE_WEBADMIN_CLIENT_ID=<service-client-id>
TIMEBASE_WEBADMIN_CLIENT_SECRET=<client-secret>
TIMEBASE_WEBADMIN_SCOPE=<api-scope>
```

### Managed bearer-token file

Use this profile when another process acquires and rotates a WebAdmin API access token. Have that process atomically replace a private file containing one ASCII token, optionally followed by a newline, of at most 32 KiB.

```dotenv
TIMEBASE_WEBADMIN_AUTH_MODE=bearer_file
TIMEBASE_WEBADMIN_TOKEN_FILE=/absolute/path/to/token
```

## 3. Apply the configuration

For local `stdio`, set the variables in your MCP client's environment configuration. For remote HTTP, set them in the MCP server's environment. Make private-key or token files available at paths the MCP process can read. For multiple instances, use the [per-instance mappings](reference/multi-server.md#optional-webadmin-settings).

Restart MCP after changing the configuration.

## 4. Verify access

1. Call `get_webadmin_info` to check the selected instance's URL and advertised provider. This tool uses public endpoints and does not verify credentials.
2. Call `list_webadmin_views` for the same instance. Complete browser sign-in if using the interactive profile. A successful response verifies that the configured identity can read views, even if the list is empty.
3. Call the protected tool for the view, topic, task, or report you intend to inspect. 

Supply `instance_key` when selecting among multiple instances. If WebAdmin tools are absent, check the URL and restart MCP. HTTP 401 indicates rejected authentication; HTTP 403 indicates insufficient permission. For mode restrictions, errors, and result limits, see the [WebAdmin reference](reference/webadmin.md).
