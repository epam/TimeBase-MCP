import logging
import asyncio
import pytest
import threading
import time
from collections.abc import Awaitable, Callable
from typing import cast

import timebase_mcp.operations as operations_module
from timebase_mcp.clients.base import TimeBaseClient
from timebase_mcp.config import MCPSettings
from timebase_mcp.errors import (
    TimeBaseConnectionError,
    TimeBaseOperationError,
    TimeBaseOperationLimitError,
    TimeBaseOperationStateError,
    TimeBaseOperationTimeoutError,
)
from timebase_mcp.operations import run_with_runtime
from timebase_mcp.pool import TimeBaseConnectionPool, TimeBaseOperationBudget
from timebase_mcp.runtime import build_runtime

_ASYNCIO_WAIT_FOR = asyncio.wait_for


class StubClient:
    def __init__(self, *, key: str, read_only: bool) -> None:
        self.key = key
        self.read_only = read_only
        self.close_calls = 0
        self.interrupt_calls = 0
        self.closed_event = threading.Event()
        self._closed = False

    def close(self) -> None:
        if self._closed:
            return

        self._closed = True
        self.close_calls += 1
        self.closed_event.set()

    def interrupt(self) -> None:
        self.interrupt_calls += 1
        self.close()


def _assert_writable_open_requested(read_only: bool) -> None:
    assert read_only is False


def _wait_for_test_release(
    event: threading.Event,
    failure_message: str = "Timed out waiting for test release event.",
) -> None:
    if not event.wait(timeout=5):
        raise AssertionError(failure_message)


async def _wait_until(
    predicate: Callable[[], bool],
    failure_message: str,
    *,
    timeout_seconds: float = 2.0,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.01)

    pytest.fail(failure_message)


async def _run_when_budget_is_released(runtime) -> int:
    result = None
    deadline = time.monotonic() + 2.0

    while time.monotonic() < deadline:
        try:
            result = await run_with_runtime(runtime, lambda client: id(client))
            assert result is not None
            return result
        except TimeBaseOperationLimitError:
            await asyncio.sleep(0.01)

    pytest.fail("Timed-out client did not release the shared operation budget.")


async def _with_timeout(awaitable: Awaitable[object], failure_message: str) -> object:
    try:
        return await _ASYNCIO_WAIT_FOR(awaitable, timeout=1.0)
    except TimeoutError:
        pytest.fail(failure_message)


async def _wait_for_thread_event(
    event: threading.Event,
    failure_message: str,
    *,
    timeout_seconds: float = 2.0,
) -> None:
    await _wait_until(event.is_set, failure_message, timeout_seconds=timeout_seconds)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_run_with_runtime_reuses_client_from_instance_pool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created_clients: list[StubClient] = []

    def build_client(instance, *, read_only: bool = False) -> StubClient:
        _assert_writable_open_requested(read_only)
        client = StubClient(key=instance.key, read_only=read_only)
        created_clients.append(client)
        return client

    monkeypatch.setattr(
        "timebase_mcp.clients.factory.create_timebase_client", build_client
    )

    runtime = build_runtime(MCPSettings())

    first_client_id = await run_with_runtime(runtime, lambda client: id(client))
    second_client_id = await run_with_runtime(runtime, lambda client: id(client))

    assert first_client_id == second_client_id
    assert len(created_clients) == 1
    assert created_clients[0].read_only is False

    await _with_timeout(runtime.aclose(), "Runtime close did not finish.")

    assert created_clients[0].close_calls == 1


@pytest.mark.anyio
async def test_run_with_runtime_uses_selected_instance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created_clients: list[StubClient] = []

    def build_client(instance, *, read_only: bool = False) -> StubClient:
        _assert_writable_open_requested(read_only)
        client = StubClient(key=instance.key, read_only=read_only)
        created_clients.append(client)
        return client

    monkeypatch.setattr(
        "timebase_mcp.clients.factory.create_timebase_client", build_client
    )

    runtime = build_runtime(
        MCPSettings.model_validate(
            {
                "servers": [
                    {"name": "prod", "url": "dxtick://prod:8011"},
                    {"name": "dev", "url": "dxtick://dev:8011"},
                ]
            }
        )
    )

    selected_key = await run_with_runtime(
        runtime,
        lambda client: cast(StubClient, client).key,
        instance_key="dev",
    )

    assert selected_key == "dev"
    assert [client.key for client in created_clients] == ["dev"]

    await _with_timeout(runtime.aclose(), "Runtime close did not finish.")


@pytest.mark.anyio
async def test_run_with_runtime_requires_instance_key_when_multiple_instances() -> None:
    runtime = build_runtime(
        MCPSettings.model_validate(
            {
                "servers": [
                    {"name": "prod", "url": "dxtick://prod:8011"},
                    {"name": "dev", "url": "dxtick://dev:8011"},
                ]
            }
        )
    )

    with pytest.raises(
        TimeBaseOperationError,
        match="instance_key is required when multiple TimeBase instances are configured",
    ):
        await run_with_runtime(runtime, lambda client: id(client))


@pytest.mark.anyio
async def test_run_with_runtime_uses_only_instance_when_key_is_omitted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created_clients: list[StubClient] = []

    def build_client(instance, *, read_only: bool = False) -> StubClient:
        _assert_writable_open_requested(read_only)
        client = StubClient(key=instance.key, read_only=read_only)
        created_clients.append(client)
        return client

    monkeypatch.setattr(
        "timebase_mcp.clients.factory.create_timebase_client", build_client
    )

    runtime = build_runtime(
        MCPSettings.model_validate(
            {"servers": [{"name": "prod", "url": "dxtick://prod:8011"}]}
        )
    )

    selected_key = await run_with_runtime(
        runtime,
        lambda client: cast(StubClient, client).key,
    )

    assert selected_key == "prod"
    assert [client.key for client in created_clients] == ["prod"]

    await _with_timeout(runtime.aclose(), "Runtime close did not finish.")


@pytest.mark.anyio
async def test_run_with_runtime_closes_broken_client_after_connection_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created_clients: list[StubClient] = []

    def build_client(instance, *, read_only: bool = False) -> StubClient:
        _assert_writable_open_requested(read_only)
        client = StubClient(key=instance.key, read_only=read_only)
        created_clients.append(client)
        return client

    monkeypatch.setattr(
        "timebase_mcp.clients.factory.create_timebase_client", build_client
    )

    runtime = build_runtime(MCPSettings())

    def broken_operation(_client: TimeBaseClient) -> None:
        raise TimeBaseConnectionError("broken connection")

    with pytest.raises(TimeBaseOperationError, match="broken connection"):
        await run_with_runtime(runtime, broken_operation)

    assert len(created_clients) == 1
    assert created_clients[0].close_calls == 1

    second_client_id = await run_with_runtime(runtime, lambda client: id(client))

    assert len(created_clients) == 2
    assert second_client_id == id(created_clients[1])

    await _with_timeout(runtime.aclose(), "Runtime close did not finish.")

    assert created_clients[1].close_calls == 1


@pytest.mark.anyio
async def test_run_with_runtime_retries_after_client_creation_connection_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created_clients: list[StubClient] = []
    create_attempts = 0

    def build_client(instance, *, read_only: bool = False) -> StubClient:
        nonlocal create_attempts
        _assert_writable_open_requested(read_only)
        create_attempts += 1
        if create_attempts == 1:
            raise TimeBaseConnectionError("connection refused")

        client = StubClient(key=instance.key, read_only=read_only)
        created_clients.append(client)
        return client

    monkeypatch.setattr(
        "timebase_mcp.clients.factory.create_timebase_client", build_client
    )

    runtime = build_runtime(MCPSettings())

    with pytest.raises(TimeBaseOperationError, match="connection refused"):
        await run_with_runtime(runtime, lambda client: id(client))

    second_client_id = await run_with_runtime(runtime, lambda client: id(client))

    assert create_attempts == 2
    assert len(created_clients) == 1
    assert created_clients[0].read_only is False
    assert second_client_id == id(created_clients[0])

    await _with_timeout(runtime.aclose(), "Runtime close did not finish.")

    assert created_clients[0].close_calls == 1


@pytest.mark.anyio
async def test_run_with_runtime_propagates_client_creation_errors_without_reuse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    create_attempts = 0

    def build_client(instance, *, read_only: bool = False) -> StubClient:
        nonlocal create_attempts
        _assert_writable_open_requested(read_only)
        create_attempts += 1
        raise TimeBaseConnectionError("connection refused")

    monkeypatch.setattr(
        "timebase_mcp.clients.factory.create_timebase_client", build_client
    )

    runtime = build_runtime(MCPSettings())

    with pytest.raises(TimeBaseOperationError, match="connection refused"):
        await run_with_runtime(runtime, lambda client: id(client))

    assert create_attempts == 1
    assert runtime.default_instance.connection_pool is None

    await _with_timeout(runtime.aclose(), "Runtime close did not finish.")


@pytest.mark.anyio
async def test_run_with_runtime_rebuilds_pool_after_connection_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created_clients: list[StubClient] = []
    create_attempts = 0
    allow_background_release = threading.Event()
    background_client: TimeBaseClient | None = None

    def build_client(instance, *, read_only: bool = False) -> StubClient:
        nonlocal create_attempts
        _assert_writable_open_requested(read_only)
        create_attempts += 1
        client = StubClient(key=instance.key, read_only=read_only)
        created_clients.append(client)
        return client

    monkeypatch.setattr(
        "timebase_mcp.clients.factory.create_timebase_client", build_client
    )

    runtime = build_runtime(MCPSettings())

    await run_with_runtime(runtime, lambda client: id(client))

    def hold_client(client: TimeBaseClient) -> int:
        nonlocal background_client
        background_client = client
        _wait_for_test_release(
            allow_background_release,
            "Background operation was not released.",
        )
        return id(client)

    background_task = asyncio.create_task(run_with_runtime(runtime, hold_client))

    await _wait_until(
        lambda: background_client is not None,
        "Background operation did not acquire a client.",
    )

    def broken_operation(_client: TimeBaseClient) -> None:
        raise TimeBaseConnectionError("connection dropped")

    with pytest.raises(TimeBaseOperationError, match="connection dropped"):
        await run_with_runtime(runtime, broken_operation)

    assert runtime.default_instance.connection_pool is None

    allow_background_release.set()
    await _with_timeout(
        background_task,
        "Background operation did not finish after release.",
    )

    await run_with_runtime(runtime, lambda client: id(client))

    assert create_attempts == 3

    await _with_timeout(runtime.aclose(), "Runtime close did not finish.")

    assert [client.close_calls for client in created_clients] == [1, 1, 1]


@pytest.mark.anyio
async def test_connection_pool_closes_client_created_after_pool_close() -> None:
    created_client = StubClient(key="default", read_only=False)
    creator_started = threading.Event()
    allow_creation_finish = threading.Event()

    def create_client() -> StubClient:
        creator_started.set()
        _wait_for_test_release(
            allow_creation_finish,
            "Client creation was not released.",
        )
        return created_client

    pool = TimeBaseConnectionPool(
        instance_key="default",
        create_client=create_client,
    )

    acquire_task = asyncio.create_task(pool.acquire())

    await _wait_for_thread_event(
        creator_started,
        "Client creation did not start.",
    )

    await pool.aclose()
    allow_creation_finish.set()

    with pytest.raises(TimeBaseOperationStateError, match="is closed"):
        await acquire_task

    assert created_client.close_calls == 1


@pytest.mark.anyio
async def test_connection_pool_closes_late_client_after_cancelled_acquire() -> None:
    late_client = StubClient(key="default", read_only=False)
    next_client = StubClient(key="default", read_only=False)
    creator_started = threading.Event()
    release_first_create = threading.Event()
    create_attempts = 0

    def create_client() -> StubClient:
        nonlocal create_attempts
        create_attempts += 1
        if create_attempts == 1:
            creator_started.set()
            _wait_for_test_release(
                release_first_create,
                "First client creation was not released.",
            )
            return late_client
        return next_client

    pool = TimeBaseConnectionPool(
        instance_key="default",
        create_client=create_client,
        operation_budget=TimeBaseOperationBudget(max_concurrent_operations=1),
    )

    acquire_task = asyncio.create_task(pool.acquire())

    await _wait_for_thread_event(
        creator_started,
        "Client creation did not start.",
    )

    acquire_task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await acquire_task

    release_first_create.set()

    await _wait_until(
        lambda: late_client.close_calls == 1,
        "Late client was not closed after cancelled acquire.",
    )

    lease = await pool.acquire()

    try:
        assert lease.client is next_client
    finally:
        await lease.aclose()
        await pool.aclose()

    assert late_client.close_calls == 1
    assert next_client.close_calls == 1


@pytest.mark.anyio
async def test_connection_pool_aclose_waits_for_background_tasks() -> None:
    pool = TimeBaseConnectionPool(
        instance_key="default",
        create_client=lambda: StubClient(key="default", read_only=False),
    )
    allow_cleanup_finish = asyncio.Event()
    cleanup_finished = asyncio.Event()

    async def background_cleanup() -> None:
        await allow_cleanup_finish.wait()
        cleanup_finished.set()

    pool.start_background_task(background_cleanup())

    close_task = asyncio.create_task(pool.aclose())
    await _wait_until(
        lambda: len(pool._close_barrier_tasks) == 1,
        "Background cleanup task was not registered.",
    )

    assert close_task.done() is False

    allow_cleanup_finish.set()
    await _with_timeout(close_task, "Connection pool close did not finish.")

    assert cleanup_finished.is_set()


@pytest.mark.anyio
async def test_connection_pool_aclose_does_not_wait_for_detached_background_tasks() -> (
    None
):
    pool = TimeBaseConnectionPool(
        instance_key="default",
        create_client=lambda: StubClient(key="default", read_only=False),
    )
    allow_cleanup_finish = asyncio.Event()
    cleanup_finished = asyncio.Event()

    async def detached_cleanup() -> None:
        await allow_cleanup_finish.wait()
        cleanup_finished.set()

    pool.start_detached_background_task(detached_cleanup())

    await _with_timeout(
        pool.aclose(),
        "Connection pool close waited for a detached background task.",
    )

    assert cleanup_finished.is_set() is False

    allow_cleanup_finish.set()

    await _wait_until(
        cleanup_finished.is_set,
        "Detached background cleanup did not complete after pool close.",
    )


@pytest.mark.anyio
async def test_run_with_runtime_fails_fast_when_global_budget_is_exhausted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created_clients: list[StubClient] = []
    release_first_operation = threading.Event()
    first_client_ready = threading.Event()

    def build_client(instance, *, read_only: bool = False) -> StubClient:
        _assert_writable_open_requested(read_only)
        client = StubClient(key=instance.key, read_only=read_only)
        created_clients.append(client)
        return client

    monkeypatch.setattr(
        "timebase_mcp.clients.factory.create_timebase_client", build_client
    )

    runtime = build_runtime(MCPSettings(max_concurrent_ops=1))

    def hold_client(client: TimeBaseClient) -> int:
        first_client_ready.set()
        _wait_for_test_release(
            release_first_operation,
            "First operation was not released.",
        )
        return id(client)

    first_operation = asyncio.create_task(run_with_runtime(runtime, hold_client))

    await _wait_for_thread_event(
        first_client_ready,
        "First operation did not acquire a client.",
    )

    with pytest.raises(
        TimeBaseOperationLimitError,
        match="Maximum concurrent TimeBase operations",
    ):
        await run_with_runtime(runtime, lambda client: id(client))

    release_first_operation.set()
    await _with_timeout(
        first_operation,
        "First operation did not finish after release.",
    )
    await _with_timeout(runtime.aclose(), "Runtime close did not finish.")

    assert len(created_clients) == 1
    assert created_clients[0].close_calls == 1


@pytest.mark.anyio
async def test_run_with_runtime_timeout_interrupts_client_and_releases_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created_clients: list[StubClient] = []

    def build_client(instance, *, read_only: bool = False) -> StubClient:
        _assert_writable_open_requested(read_only)
        client = StubClient(key=instance.key, read_only=read_only)
        created_clients.append(client)
        return client

    monkeypatch.setattr(
        "timebase_mcp.clients.factory.create_timebase_client", build_client
    )

    runtime = build_runtime(
        MCPSettings(operation_timeout_seconds=1, max_concurrent_ops=1)
    )
    initial_pool = runtime.default_instance.get_connection_pool()

    def slow_operation(client: TimeBaseClient) -> int:
        stub_client = cast(StubClient, client)
        _wait_for_test_release(
            stub_client.closed_event,
            "Timed-out client was not closed.",
        )
        return id(stub_client)

    with pytest.raises(
        TimeBaseOperationTimeoutError,
        match="timed out after 1 second",
    ):
        await run_with_runtime(runtime, slow_operation)

    assert runtime.default_instance.connection_pool is initial_pool

    await _wait_until(
        lambda: bool(
            created_clients
            and created_clients[0].interrupt_calls == 1
            and created_clients[0].close_calls == 1
        ),
        "Timed-out client was not interrupted and closed.",
    )

    second_client_id = await _run_when_budget_is_released(runtime)

    assert len(created_clients) == 2
    assert runtime.default_instance.connection_pool is initial_pool
    assert created_clients[0].interrupt_calls == 1
    assert created_clients[0].close_calls == 1
    assert second_client_id == id(created_clients[1])

    await _with_timeout(runtime.aclose(), "Runtime close did not finish.")

    assert created_clients[1].close_calls == 1


@pytest.mark.anyio
async def test_run_with_runtime_returns_completed_result_when_timeout_races_completion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created_clients: list[StubClient] = []

    def build_client(instance, *, read_only: bool = False) -> StubClient:
        _assert_writable_open_requested(read_only)
        client = StubClient(key=instance.key, read_only=read_only)
        created_clients.append(client)
        return client

    async def fake_wait_for(awaitable, timeout):
        assert timeout == 1
        await awaitable
        raise TimeoutError

    monkeypatch.setattr(
        "timebase_mcp.clients.factory.create_timebase_client", build_client
    )
    monkeypatch.setattr(operations_module.asyncio, "wait_for", fake_wait_for)

    runtime = build_runtime(MCPSettings(operation_timeout_seconds=1))

    result = await run_with_runtime(runtime, lambda client: id(client))

    assert result == id(created_clients[0])

    await _with_timeout(runtime.aclose(), "Runtime close did not finish.")

    assert created_clients[0].close_calls == 1


@pytest.mark.anyio
async def test_run_with_runtime_timeout_logs_interrupt_failure_and_releases_budget(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    class InterruptFailingClient(StubClient):
        def interrupt(self) -> None:
            self.interrupt_calls += 1
            self.close()
            raise RuntimeError("interrupt failed")

    created_clients: list[InterruptFailingClient] = []
    allow_operation_finish = threading.Event()

    def build_client(instance, *, read_only: bool = False) -> InterruptFailingClient:
        _assert_writable_open_requested(read_only)
        client = InterruptFailingClient(key=instance.key, read_only=read_only)
        created_clients.append(client)
        return client

    def slow_operation(client: TimeBaseClient) -> int:
        stub_client = cast(StubClient, client)
        _wait_for_test_release(
            stub_client.closed_event,
            "Timed-out client was not closed.",
        )
        _wait_for_test_release(
            allow_operation_finish,
            "Interrupted operation was not released.",
        )
        return id(stub_client)

    monkeypatch.setattr(
        "timebase_mcp.clients.factory.create_timebase_client", build_client
    )

    runtime = build_runtime(
        MCPSettings(operation_timeout_seconds=1, max_concurrent_ops=1)
    )

    with caplog.at_level(logging.WARNING):
        with pytest.raises(
            TimeBaseOperationTimeoutError,
            match="timed out after 1 second",
        ):
            await run_with_runtime(runtime, slow_operation)

    assert "Failed to interrupt TimeBase operation for instance default" in caplog.text
    assert "interrupt failed" in caplog.text

    allow_operation_finish.set()
    next_client_id = await _run_when_budget_is_released(runtime)

    assert len(created_clients) == 2
    assert created_clients[0].interrupt_calls == 1
    assert created_clients[0].close_calls == 1
    assert next_client_id == id(created_clients[1])

    await _with_timeout(runtime.aclose(), "Runtime close did not finish.")

    assert created_clients[1].close_calls == 1


@pytest.mark.anyio
async def test_run_with_runtime_timeout_does_not_block_runtime_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release_operation = threading.Event()

    class NonInterruptingClient(StubClient):
        def interrupt(self) -> None:
            self.interrupt_calls += 1

    created_clients: list[NonInterruptingClient] = []

    def build_client(instance, *, read_only: bool = False) -> NonInterruptingClient:
        _assert_writable_open_requested(read_only)
        client = NonInterruptingClient(key=instance.key, read_only=read_only)
        created_clients.append(client)
        return client

    def slow_operation(_client: TimeBaseClient) -> int:
        _wait_for_test_release(
            release_operation,
            "Timed-out operation was not released.",
        )
        return 1

    monkeypatch.setattr(
        "timebase_mcp.clients.factory.create_timebase_client", build_client
    )

    runtime = build_runtime(MCPSettings(operation_timeout_seconds=1))

    with pytest.raises(
        TimeBaseOperationTimeoutError,
        match="timed out after 1 second",
    ):
        await run_with_runtime(runtime, slow_operation)

    await _with_timeout(
        runtime.aclose(),
        "Runtime close waited for a detached timed-out operation.",
    )

    assert created_clients[0].interrupt_calls == 1
    assert created_clients[0].close_calls == 0

    release_operation.set()

    await _wait_until(
        lambda: created_clients[0].close_calls == 1,
        "Timed-out client was not eventually closed after shutdown.",
    )
