import asyncio
import logging
from collections.abc import Callable
from typing import TypeVar

from mcp.server.fastmcp import Context
from mcp.server.session import ServerSession

from timebase_mcp.auth.principal import current_principal
from timebase_mcp.clients.base import TimeBaseClient
from timebase_mcp.constants import SHARED_PRINCIPAL_KEY
from timebase_mcp.errors import (
    TimeBaseConnectionError,
    TimeBaseMCPError,
    TimeBaseOperationError,
    TimeBaseOperationStateError,
    TimeBaseOperationTimeoutError,
)
from timebase_mcp.instance import TimeBaseInstanceRuntime
from timebase_mcp.pool import TimeBaseConnectionPool
from timebase_mcp.runtime import TimeBaseRuntime

ResultT = TypeVar("ResultT")
logger = logging.getLogger(__name__)


def _resolve_pool(
    instance: TimeBaseInstanceRuntime,
) -> tuple[str, TimeBaseConnectionPool[TimeBaseClient]]:
    """Select the connection pool for the operation.

    Returns ``(principal_key, pool)``. ``forward_identity`` instances use a pool
    per authenticated caller; every other mode shares one pool.
    """
    if instance.config.auth_mode == "forward_identity":
        principal = current_principal()
        if principal is None or not principal.token:
            raise TimeBaseOperationStateError(
                f"TimeBase server '{instance.key}' forwards caller identity but the "
                "request is not authenticated."
            )
        return principal.subject, instance.get_principal_pool(
            principal.subject,
            principal.token,
            principal.username,
        )

    return SHARED_PRINCIPAL_KEY, instance.get_connection_pool()


async def run_with_runtime(
    runtime: TimeBaseRuntime,
    operation: Callable[[TimeBaseClient], ResultT],
    *,
    instance_key: str | None = None,
) -> ResultT:
    """Run a TimeBase operation against a resolved runtime instance."""
    instance = runtime.get_instance(instance_key)
    principal_key, pool = _resolve_pool(instance)
    timeout_seconds = runtime.server_settings.operation_timeout_seconds
    lease = None
    operation_future = None
    release_lease_in_background = False

    try:
        lease = await pool.acquire()
        operation_future = asyncio.get_running_loop().run_in_executor(
            None,
            operation,
            lease.client,
        )

        if timeout_seconds > 0:
            try:
                return await asyncio.wait_for(
                    asyncio.shield(operation_future),
                    timeout=timeout_seconds,
                )
            except TimeoutError as exc:
                if operation_future.done():
                    return await operation_future

                release_lease_in_background = await _interrupt_operation(
                    lease,
                    operation_future,
                    instance_key=instance.key,
                )
                raise TimeBaseOperationTimeoutError(
                    f"TimeBase operation timed out after {timeout_seconds} seconds."
                ) from exc

        return await asyncio.shield(operation_future)
    except asyncio.CancelledError:
        if (
            lease is not None
            and operation_future is not None
            and not operation_future.done()
        ):
            release_lease_in_background = await _interrupt_operation(
                lease,
                operation_future,
                instance_key=instance.key,
            )
        raise
    except TimeBaseConnectionError as exc:
        if lease is not None:
            lease.mark_broken()
        await instance.reset_connection_state(principal_key)
        logger.warning(
            "TimeBase connection failed for instance %s: %s",
            instance.key,
            exc,
            exc_info=True,
        )
        raise TimeBaseOperationError(str(exc)) from exc
    except TimeBaseMCPError:
        raise
    except ValueError as exc:
        raise TimeBaseOperationError(str(exc)) from exc
    except Exception as exc:
        logger.error(
            "Unexpected error during TimeBase operation for instance %s",
            instance.key,
            exc_info=True,
        )
        raise TimeBaseOperationError(str(exc)) from exc
    finally:
        if lease is not None and not release_lease_in_background:
            await lease.aclose()


async def run_with_context(
    ctx: Context[ServerSession, TimeBaseRuntime],
    operation: Callable[[TimeBaseClient], ResultT],
    *,
    instance_key: str | None = None,
) -> ResultT:
    runtime = ctx.request_context.lifespan_context
    return await run_with_runtime(
        runtime,
        operation,
        instance_key=instance_key,
    )


async def _release_lease_after_operation(
    operation_future: asyncio.Future[ResultT],
    lease,
) -> None:
    try:
        await operation_future
    except Exception:
        pass
    finally:
        await lease.aclose()


async def _interrupt_operation(
    lease,
    operation_future: asyncio.Future[ResultT],
    *,
    instance_key: str,
) -> bool:
    lease.mark_broken()

    try:
        await asyncio.to_thread(lease.client.interrupt)
    except Exception as exc:
        logger.warning(
            "Failed to interrupt TimeBase operation for instance %s: %s",
            instance_key,
            exc,
            exc_info=True,
        )

    if operation_future.done():
        return False

    lease.pool.start_detached_background_task(
        _release_lease_after_operation(operation_future, lease)
    )
    return True
