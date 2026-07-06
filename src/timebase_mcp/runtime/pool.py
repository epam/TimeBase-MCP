from __future__ import annotations

import asyncio
import logging
from collections import deque
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from typing import Any, Generic, Protocol, TypeVar

from timebase_mcp.errors import TimeBaseOperationLimitError, TimeBaseOperationStateError

DEFAULT_MAX_IDLE_CLIENTS = 1
logger = logging.getLogger(__name__)


class ClosableClient(Protocol):
    """Minimal client lifecycle surface required by the runtime pool."""

    def close(self) -> None: ...


ClientT = TypeVar("ClientT", bound=ClosableClient)
ClientCreator = Callable[[], ClientT]


@dataclass(slots=True)
class TimeBaseOperationBudget:
    """Shared fail-fast budget for concurrent TimeBase operations."""

    max_concurrent_operations: int = 0
    _active_operations: int = field(default=0, init=False, repr=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)

    async def acquire(self) -> None:
        if self.max_concurrent_operations == 0:
            return

        async with self._lock:
            if self._active_operations >= self.max_concurrent_operations:
                raise TimeBaseOperationLimitError(
                    "Maximum concurrent TimeBase operations reached."
                )

            self._active_operations += 1

    async def release(self) -> None:
        if self.max_concurrent_operations == 0:
            return

        async with self._lock:
            if self._active_operations > 0:
                self._active_operations -= 1


@dataclass(slots=True)
class TimeBaseConnectionLease(Generic[ClientT]):
    """Exclusive lease for a pooled TimeBase client."""

    pool: TimeBaseConnectionPool[ClientT]
    client: ClientT
    _is_broken: bool = field(default=False, init=False, repr=False)
    _closed: bool = field(default=False, init=False, repr=False)

    def mark_broken(self) -> None:
        self._is_broken = True

    async def aclose(self) -> None:
        if self._closed:
            return

        self._closed = True
        await self.pool.check_in(self.client, reusable=not self._is_broken)


@dataclass(slots=True)
class TimeBaseConnectionPool(Generic[ClientT]):
    """Runtime-owned pool of reusable TimeBase clients for one instance."""

    instance_key: str
    create_client: ClientCreator[ClientT]
    operation_budget: TimeBaseOperationBudget = field(
        default_factory=TimeBaseOperationBudget
    )
    max_idle_clients: int = DEFAULT_MAX_IDLE_CLIENTS
    _idle_clients: deque[ClientT] = field(
        default_factory=deque,
        init=False,
        repr=False,
    )
    _background_tasks: set[asyncio.Task[None]] = field(
        default_factory=set,
        init=False,
        repr=False,
    )
    _close_barrier_tasks: set[asyncio.Task[None]] = field(
        default_factory=set,
        init=False,
        repr=False,
    )
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)
    _closed: bool = field(default=False, init=False, repr=False)

    def start_background_task(
        self,
        coroutine: Coroutine[Any, Any, None],
    ) -> None:
        self._start_background_task(coroutine, blocks_close=True)

    def start_detached_background_task(
        self,
        coroutine: Coroutine[Any, Any, None],
    ) -> None:
        self._start_background_task(coroutine, blocks_close=False)

    def _start_background_task(
        self,
        coroutine: Coroutine[Any, Any, None],
        *,
        blocks_close: bool,
    ) -> None:
        task = asyncio.create_task(coroutine)
        self._background_tasks.add(task)
        if blocks_close:
            self._close_barrier_tasks.add(task)
        task.add_done_callback(self._finalize_background_task)

    async def acquire(self) -> TimeBaseConnectionLease[ClientT]:
        await self.operation_budget.acquire()

        try:
            client = await self._take_idle_client()
            if client is None:
                client = await self._create_client()

            return TimeBaseConnectionLease(pool=self, client=client)
        except BaseException:
            await self.operation_budget.release()
            raise

    async def check_in(
        self,
        client: ClientT,
        *,
        reusable: bool = True,
    ) -> None:
        try:
            should_close = not reusable
            async with self._lock:
                if (
                    self._closed
                    or not reusable
                    or len(self._idle_clients) >= self.max_idle_clients
                ):
                    should_close = True
                else:
                    self._idle_clients.append(client)

            if should_close:
                await asyncio.to_thread(client.close)
        finally:
            await self.operation_budget.release()

    async def aclose(self) -> None:
        async with self._lock:
            if self._closed:
                return

            self._closed = True
            idle_clients = list(self._idle_clients)
            self._idle_clients.clear()

        if idle_clients:
            await asyncio.gather(
                *(asyncio.to_thread(client.close) for client in idle_clients)
            )

        while self._close_barrier_tasks:
            close_barrier_tasks = tuple(self._close_barrier_tasks)
            await asyncio.gather(
                *close_barrier_tasks,
                return_exceptions=True,
            )
            self._close_barrier_tasks.difference_update(close_barrier_tasks)

    async def _take_idle_client(self) -> ClientT | None:
        async with self._lock:
            if self._closed:
                raise TimeBaseOperationStateError(
                    f"TimeBase client pool for instance '{self.instance_key}' is closed."
                )

            if not self._idle_clients:
                return None

            return self._idle_clients.pop()

    async def _create_client(self) -> ClientT:
        loop = asyncio.get_running_loop()
        create_future = loop.run_in_executor(None, self.create_client)

        try:
            client = await asyncio.shield(create_future)
        except asyncio.CancelledError:
            self.start_background_task(
                self._close_created_client_when_ready(create_future)
            )
            raise

        try:
            retired = await self._close_if_retired(client)
        except BaseException:
            await asyncio.to_thread(client.close)
            raise

        if retired:
            raise TimeBaseOperationStateError(
                f"TimeBase client pool for instance '{self.instance_key}' is closed."
            )

        return client

    async def _close_if_retired(self, client: ClientT) -> bool:
        async with self._lock:
            if not self._closed:
                return False

        await asyncio.to_thread(client.close)
        return True

    async def _close_created_client_when_ready(
        self,
        create_future: asyncio.Future[ClientT],
    ) -> None:
        try:
            client = await create_future
        except Exception:
            return

        await asyncio.to_thread(client.close)

    def _finalize_background_task(self, task: asyncio.Task[None]) -> None:
        self._background_tasks.discard(task)
        self._close_barrier_tasks.discard(task)

        try:
            task.result()
        except asyncio.CancelledError:
            return
        except Exception:
            logger.error(
                "Background cleanup failed for TimeBase pool instance %s",
                self.instance_key,
                exc_info=True,
            )
