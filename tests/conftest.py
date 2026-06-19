import pytest

from timebase_mcp.config import SETTINGS_ENV_VARS


@pytest.fixture(autouse=True)
def isolated_settings_env(
    monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest
) -> None:
    if request.node.get_closest_marker("integration") is not None:
        return

    for variable_name in SETTINGS_ENV_VARS:
        monkeypatch.delenv(variable_name, raising=False)
