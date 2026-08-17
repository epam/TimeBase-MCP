from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager

import pytest
from mcp.client import Client
from mcp.shared.exceptions import MCPError
from mcp_types import TextResourceContents

from timebase_mcp import resources as resources_module
from timebase_mcp.config.settings import MCPSettings
from timebase_mcp.errors import (
    TimeBaseOperationError,
)
from timebase_mcp.server import create_server

from tests.server.helpers import (
    ResourceCatalogClient,
    resource_text,
)


@pytest.mark.anyio
async def test_read_resources_return_expected_text(
    monkeypatch: pytest.MonkeyPatch,
    client_session_factory: Callable[
        [MCPSettings | None],
        AbstractAsyncContextManager[Client],
    ],
) -> None:
    selected_instances: list[str | None] = []

    async def run_resource(_runtime, operation, *, instance_key=None):
        selected_instances.append(instance_key)

        return operation(ResourceCatalogClient(instance_key=instance_key))

    monkeypatch.setattr(resources_module, "run_with_runtime", run_resource)

    async with client_session_factory(None) as client_session:
        catalog = await client_session.read_resource("timebase://streams")
        schema = await client_session.read_resource("timebase://streams/bars/schema")
        instance_catalog = await client_session.read_resource(
            "timebase://instances/dev/streams"
        )
        instance_schema = await client_session.read_resource(
            "timebase://instances/dev/streams/bars/schema"
        )

    catalog_text = [
        content.text
        for content in catalog.contents
        if isinstance(content, TextResourceContents)
    ]
    schema_text = [
        content.text
        for content in schema.contents
        if isinstance(content, TextResourceContents)
    ]
    instance_catalog_text = [
        content.text
        for content in instance_catalog.contents
        if isinstance(content, TextResourceContents)
    ]
    instance_schema_text = [
        content.text
        for content in instance_schema.contents
        if isinstance(content, TextResourceContents)
    ]

    assert selected_instances == [None, None, "dev", "dev"]
    assert catalog_text == ["bars: desc:None"]
    assert schema_text == ["schema:None:bars"]
    assert instance_catalog_text == ["bars: desc:dev"]
    assert instance_schema_text == ["schema:dev:bars"]


@pytest.mark.anyio
async def test_read_resource_surfaces_operation_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fail_resource(_runtime, _operation, *, instance_key=None):
        raise TimeBaseOperationError("resource failed")

    monkeypatch.setattr(resources_module, "run_with_runtime", fail_resource)

    server = create_server(MCPSettings())
    async with Client(server, raise_exceptions=False) as client_session:
        with pytest.raises(MCPError) as error_info:
            await client_session.read_resource("timebase://streams")

    assert str(error_info.value) == "resource failed"


@pytest.mark.anyio
async def test_read_unscoped_resource_requires_instance_key_when_multiple_instances() -> (
    None
):
    settings = MCPSettings.model_validate(
        {
            "servers": [
                {"name": "prod", "url": "dxtick://prod:8011"},
                {"name": "dev", "url": "dxtick://dev:8011"},
            ]
        }
    )
    server = create_server(settings)

    async with Client(server, raise_exceptions=False) as client_session:
        with pytest.raises(
            MCPError,
            match=(
                r"instance_key is required when multiple TimeBase instances "
                r"are configured"
            ),
        ):
            await client_session.read_resource("timebase://streams")


@pytest.mark.anyio
async def test_read_instance_scoped_resource_uses_selected_instance_when_multiple_instances(
    monkeypatch: pytest.MonkeyPatch,
    client_session_factory: Callable[
        [MCPSettings | None],
        AbstractAsyncContextManager[Client],
    ],
) -> None:
    selected_instances: list[str | None] = []

    async def run_resource(_runtime, operation, *, instance_key=None):
        selected_instances.append(instance_key)

        return operation(
            ResourceCatalogClient(
                instance_key=instance_key,
                description=f"from {instance_key}",
            )
        )

    monkeypatch.setattr(resources_module, "run_with_runtime", run_resource)
    settings = MCPSettings.model_validate(
        {
            "servers": [
                {"name": "prod", "url": "dxtick://prod:8011"},
                {"name": "dev", "url": "dxtick://dev:8011"},
            ]
        }
    )

    async with client_session_factory(settings) as client_session:
        catalog = await client_session.read_resource("timebase://instances/dev/streams")

    catalog_text = [
        content.text
        for content in catalog.contents
        if isinstance(content, TextResourceContents)
    ]

    assert selected_instances == ["dev"]
    assert catalog_text == ["bars: from dev"]


@pytest.mark.anyio
async def test_read_instance_scoped_resource_supports_url_instance_key(
    monkeypatch: pytest.MonkeyPatch,
    client_session_factory: Callable[
        [MCPSettings | None],
        AbstractAsyncContextManager[Client],
    ],
) -> None:
    selected_instances: list[str | None] = []

    async def run_resource(_runtime, operation, *, instance_key=None):
        selected_instances.append(instance_key)

        return operation(
            ResourceCatalogClient(
                instance_key=instance_key,
                description=f"from {instance_key}",
            )
        )

    monkeypatch.setattr(resources_module, "run_with_runtime", run_resource)
    settings = MCPSettings.model_validate(
        {
            "servers": [
                {"name": "prod", "url": "dxtick://prod:8011"},
                {"url": "dxtick://dev:8011"},
            ]
        }
    )

    async with client_session_factory(settings) as client_session:
        catalog = await client_session.read_resource(
            "timebase://instances/dxtick%3A%2F%2Fdev%3A8011/streams"
        )

    catalog_text = [
        content.text
        for content in catalog.contents
        if isinstance(content, TextResourceContents)
    ]

    assert selected_instances == ["dxtick://dev:8011"]
    assert catalog_text == ["bars: from dxtick://dev:8011"]


@pytest.mark.anyio
async def test_read_resource_template_params_are_decoded_once(
    monkeypatch: pytest.MonkeyPatch,
    client_session_factory: Callable[
        [MCPSettings | None],
        AbstractAsyncContextManager[Client],
    ],
) -> None:
    # The SDK percent-decodes template params, so decoding them again would turn
    # 'a%2Fb' into 'a/b' and address the wrong instance or stream.
    selected_instances: list[str | None] = []

    async def run_resource(_runtime, operation, *, instance_key=None):
        selected_instances.append(instance_key)

        return operation(
            ResourceCatalogClient(
                instance_key=instance_key,
                description=f"from {instance_key}",
            )
        )

    monkeypatch.setattr(resources_module, "run_with_runtime", run_resource)

    async with client_session_factory(None) as client_session:
        await client_session.read_resource("timebase://instances/a%252Fb/streams")
        stream_schema = await client_session.read_resource(
            "timebase://streams/a%252Fb/schema"
        )
        instance_stream_schema = await client_session.read_resource(
            "timebase://instances/a%252Fb/streams/c%252Fd/schema"
        )

    assert selected_instances == ["a%2Fb", None, "a%2Fb"]
    assert resource_text(stream_schema) == ["schema:None:a%2Fb"]
    assert resource_text(instance_stream_schema) == ["schema:a%2Fb:c%2Fd"]
