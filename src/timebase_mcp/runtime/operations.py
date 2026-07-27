import asyncio
import logging
from collections.abc import Callable
from typing import TypeVar

import anyio
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
from timebase_mcp.runtime.instance import TimeBaseInstanceRuntime
from timebase_mcp.runtime.pool import TimeBaseConnectionLease, TimeBaseConnectionPool
from timebase_mcp.runtime.state import TimeBaseRuntime

ResultT = TypeVar("ResultT")
logger = logging.getLogger(__name__)

# Grace period to allow a cancellation to complete before escalating to an interrupt
_COOPERATIVE_STOP_GRACE_SECONDS = 2.0


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
    try:
        instance = runtime.get_instance(instance_key)
    except ValueError as exc:
        raise TimeBaseOperationError(str(exc)) from exc

    timeout_seconds = runtime.server_settings.operation_timeout_seconds
    principal_key = SHARED_PRINCIPAL_KEY
    lease = None
    operation_future = None
    release_lease_in_background = False

    try:
        principal_key, pool = _resolve_pool(instance)
        lease = await pool.acquire()
        lease.client.bind_operation()
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

                release_lease_in_background = _begin_stop(
                    lease,
                    operation_future,
                    instance_key=instance.key,
                    reason="operation timeout",
                )
                raise TimeBaseOperationTimeoutError(
                    f"TimeBase operation timed out after {timeout_seconds} seconds."
                ) from exc

        return await asyncio.shield(operation_future)
    except asyncio.CancelledError:
        # We are inside an already-cancelled scope, so we must not await here:
        # anyio re-cancels awaits made in a cancelled scope, which would skip
        # cleanup. Initiate the stop synchronously and hand off the rest.
        if (
            lease is not None
            and operation_future is not None
            and not operation_future.done()
        ):
            release_lease_in_background = _begin_stop(
                lease,
                operation_future,
                instance_key=instance.key,
                reason="client cancellation",
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


def _begin_stop(
    lease: TimeBaseConnectionLease[TimeBaseClient],
    operation_future: asyncio.Future[ResultT],
    *,
    instance_key: str,
    reason: str,
) -> bool:
    """Triggers a graceful stop. Returns True if lease release was deferred.

    Never awaits, so it also works inside an already-cancelled scope.
    """
    logger.info(
        "Stopping TimeBase operation for instance %s (%s) after %d row(s).",
        instance_key,
        reason,
        lease.client.rows_read,
    )
    lease.client.request_cancel()

    if operation_future.done():
        return False

    lease.pool.start_detached_background_task(
        _finalize_stopped_operation(
            operation_future,
            lease,
            instance_key=instance_key,
            reason=reason,
        )
    )
    return True


async def _finalize_stopped_operation(
    operation_future: asyncio.Future[ResultT],
    lease: TimeBaseConnectionLease[TimeBaseClient],
    *,
    instance_key: str,
    reason: str,
) -> None:
    """Waits for a stopped operation to unwind, escalating if needed.

    Runs detached, outside the cancelled request scope, so awaiting is safe here.
    """
    started = time.monotonic()
    try:
        try:
            await asyncio.wait_for(
                asyncio.shield(operation_future),
                timeout=_COOPERATIVE_STOP_GRACE_SECONDS,
            )
        except TimeoutError:
            await _escalate_to_interrupt(
                operation_future,
                lease,
                instance_key=instance_key,
                reason=reason,
            )
        except Exception:
            lease.mark_broken()
            logger.debug(
                "TimeBase operation for instance %s raised while stopping (%s).",
                instance_key,
                reason,
                exc_info=True,
            )
        else:
            logger.info(
                "TimeBase operation for instance %s stopped cooperatively in %.2fs "
                "(%s), connection reused.",
                instance_key,
                time.monotonic() - started,
                reason,
            )
    finally:
        await lease.aclose()


async def _escalate_to_interrupt(
    operation_future: asyncio.Future[ResultT],
    lease: TimeBaseConnectionLease[TimeBaseClient],
    *,
    instance_key: str,
    reason: str,
) -> None:
    lease.mark_broken()
    logger.warning(
        "TimeBase operation for instance %s did not stop within %.1fs (%s), "
        "closing the connection.",
        instance_key,
        _COOPERATIVE_STOP_GRACE_SECONDS,
        reason,
    )

    try:
        await asyncio.to_thread(lease.client.interrupt)
    except Exception as exc:
        logger.warning(
            "Failed to interrupt TimeBase operation for instance %s: %s",
            instance_key,
            exc,
            exc_info=True,
        )

    # Unbounded on purpose. If interrupt fails to unblock the native call this
    # never returns, so the lease is never released.
    try:
        await operation_future
    except Exception:
        logger.debug(
            "Interrupted TimeBase operation for instance %s ended with an error.",
            instance_key,
            exc_info=True,
        )


