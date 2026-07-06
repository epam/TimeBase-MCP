import os
from collections.abc import Generator

import pytest

from timebase_mcp.config.env import DXAPI_SSL_TERMINATION_ENV, DXAPI_SSL_TRUST_ALL_ENV
from timebase_mcp.config.settings import SETTINGS_ENV_VARS

_DXAPI_SSL_ENV_VARS = (DXAPI_SSL_TERMINATION_ENV, DXAPI_SSL_TRUST_ALL_ENV)


@pytest.fixture(autouse=True)
def isolated_settings_env(
    monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest
) -> None:
    if request.node.get_closest_marker("integration") is not None:
        return

    for variable_name in SETTINGS_ENV_VARS:
        monkeypatch.delenv(variable_name, raising=False)


@pytest.fixture(autouse=True)
def isolated_dxapi_ssl_env(
    request: pytest.FixtureRequest,
) -> Generator[None, None, None]:
    if request.node.get_closest_marker("integration") is not None:
        yield
        return

    saved = {name: os.environ.get(name) for name in _DXAPI_SSL_ENV_VARS}
    for name in _DXAPI_SSL_ENV_VARS:
        os.environ.pop(name, None)
    yield
    for name, value in saved.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value
