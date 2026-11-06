import json
from pathlib import Path

from scripts.render_server_json import render_server_metadata


def test_rendered_remote_package_exposes_shared_resource_auth_settings(
    tmp_path: Path,
) -> None:
    template = tmp_path / "template.json"
    output = tmp_path / "server.json"
    template.write_text(
        json.dumps(
            {
                "version": "__VERSION__",
                "packages": [
                    {"transport": {"type": "stdio"}},
                    {"transport": {"type": "streamable-http"}},
                ],
            }
        )
    )

    render_server_metadata("0.2.7", template_path=template, output_path=output)

    data = json.loads(output.read_text())
    assert data["version"] == "0.2.7"
    local, remote = data["packages"]
    remote_env = {item["name"]: item for item in remote["environmentVariables"]}
    local_names = {item["name"] for item in local["environmentVariables"]}
    shared_resource_settings = {
        "MCP_AUTH_PUBLIC_URL",
        "MCP_AUTH_AUDIENCE",
        "MCP_AUTH_ISSUER_URL",
        "MCP_AUTH_JWKS_URL",
        "MCP_AUTH_REQUIRED_SCOPES",
        "MCP_AUTH_SCOPE_ALIASES",
    }
    assert shared_resource_settings <= remote_env.keys()
    assert shared_resource_settings.isdisjoint(local_names)
    assert remote_env["MCP_AUTH_SCOPE_ALIASES"]["format"] == "string"
    assert len(remote_env) == len(remote["environmentVariables"])
