import pytest
from pydantic import SecretStr

from timebase_mcp.config.settings import MCPSettings
from timebase_mcp.config.webadmin import WebAdminAuthConfig, WebAdminConfig
from timebase_mcp.runtime.instance import TimeBaseInstanceRuntime
from timebase_mcp.runtime.state import build_runtime


@pytest.fixture
def webadmin_instance() -> TimeBaseInstanceRuntime:
    return build_runtime(
        MCPSettings(
            webadmin=WebAdminConfig(
                url="http://webadmin.example.com",
                auth=WebAdminAuthConfig(
                    username="admin",
                    password=SecretStr("user-password"),
                    client_id="client-id",
                    client_secret=SecretStr("client-secret"),
                ),
            ),
        )
    ).get_instance()
