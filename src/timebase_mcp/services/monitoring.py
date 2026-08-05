from __future__ import annotations

import asyncio
import contextvars
from collections.abc import Callable
from typing import Any, Literal, TypeVar
from urllib.parse import urlencode

import httpx2

from timebase_mcp.errors import TimeBaseOperationError, TimeBaseOperationTimeoutError
from timebase_mcp.runtime.instance import TimeBaseInstanceRuntime
from timebase_mcp.models.monitoring import (
    TimeBaseActivityDetail,
    TimeBaseActivityList,
    TimeBaseConnectionActivity,
    TimeBaseCursorActivity,
    TimeBaseLicenseSummary,
    TimeBaseLoaderActivity,
    TimeBaseLockActivity,
    TimeBaseRuntimeSummary,
    TimeBaseSecuritySummary,
    TimeBaseStatus,
)
from timebase_mcp.runtime.state import TimeBaseRuntime
from timebase_mcp.clients.http.responses import (
    response_json_dict,
    response_json_list,
)
from timebase_mcp.clients.http.transport import timebase_http_request
from timebase_mcp.clients.http.urls import quote_path_segment

ResultT = TypeVar("ResultT")
ActivityKind = Literal["all", "cursors", "loaders", "connections", "locks"]
DetailKind = Literal["cursor", "loader", "connection", "lock"]


async def _run_monitor_operation(
    runtime: TimeBaseRuntime,
    operation: Callable[[TimeBaseInstanceRuntime], ResultT],
    *,
    instance_key: str | None = None,
) -> ResultT:
    try:
        instance = runtime.get_instance(instance_key)
    except ValueError as exc:
        raise TimeBaseOperationError(str(exc)) from exc

    await runtime.operation_budget.acquire()
    try:
        context = contextvars.copy_context()

        def run_operation_in_context() -> ResultT:
            return context.run(operation, instance)

        future = asyncio.get_running_loop().run_in_executor(
            None,
            run_operation_in_context,
        )
        timeout_seconds = runtime.server_settings.operation_timeout_seconds
        if timeout_seconds > 0:
            try:
                return await asyncio.wait_for(future, timeout_seconds)
            except TimeoutError as exc:
                raise TimeBaseOperationTimeoutError(
                    f"TimeBase monitor operation timed out after {timeout_seconds} seconds."
                ) from exc
        return await future
    except TimeBaseOperationError:
        raise
    except httpx2.HTTPError as exc:
        raise TimeBaseOperationError(str(exc)) from exc
    except ValueError as exc:
        raise TimeBaseOperationError(str(exc)) from exc
    except Exception as exc:
        raise TimeBaseOperationError(str(exc)) from exc
    finally:
        await runtime.operation_budget.release()


def _raise_for_required_response(response: httpx2.Response, *, endpoint: str) -> None:
    if response.status_code == 404:
        raise TimeBaseOperationError(
            f"TimeBase Monitor API endpoint {endpoint} is not available."
        )
    if response.status_code in (401, 403):
        raise TimeBaseOperationError(
            f"TimeBase Monitor API endpoint {endpoint} is not authorized. Check outbound TimeBase HTTP auth."
        )
    try:
        response.raise_for_status()
    except httpx2.HTTPStatusError as exc:
        raise TimeBaseOperationError(
            f"TimeBase Monitor API endpoint {endpoint} failed with HTTP {response.status_code}."
        ) from exc


def _required_dict(instance: TimeBaseInstanceRuntime, endpoint: str) -> dict[str, Any]:
    response = timebase_http_request(instance, endpoint)
    _raise_for_required_response(response, endpoint=endpoint)
    return response_json_dict(
        response,
        what=endpoint,
        error_factory=TimeBaseOperationError,
    )


def _optional_dict(
    instance: TimeBaseInstanceRuntime,
    endpoint: str,
    *,
    warnings: list[str],
) -> dict[str, Any] | None:
    try:
        return _required_dict(instance, endpoint)
    except Exception as exc:
        warnings.append(f"{endpoint} unavailable: {exc}")
        return None


def _status_sync(instance: TimeBaseInstanceRuntime) -> TimeBaseStatus:
    warnings: list[str] = []
    info = _required_dict(instance, "/api/info")
    license_payload = _optional_dict(instance, "/api/license", warnings=warnings)
    security_payload = _optional_dict(
        instance,
        "/api/server/security",
        warnings=warnings,
    )
    runtime_payload = _optional_dict(
        instance,
        "/api/server/system?" + urlencode({"gc": "false"}),
        warnings=warnings,
    )

    return TimeBaseStatus(
        instance_key=instance.key,
        http_url=instance.resolved_http_base_url,
        version=_str(info.get("version")),
        security=_security_summary(security_payload) if security_payload else None,
        license=_license_summary(license_payload) if license_payload else None,
        runtime=_runtime_summary(runtime_payload) if runtime_payload else None,
        warnings=warnings,
    )


async def get_timebase_status(
    runtime: TimeBaseRuntime,
    *,
    instance_key: str | None = None,
) -> TimeBaseStatus:
    return await _run_monitor_operation(
        runtime,
        _status_sync,
        instance_key=instance_key,
    )


def _activity_list_sync(
    instance: TimeBaseInstanceRuntime,
    *,
    kind: ActivityKind,
    limit: int,
) -> TimeBaseActivityList:
    warnings: list[str] = []
    result = TimeBaseActivityList(instance_key=instance.key)

    if kind in ("all", "cursors"):
        cursors = _optional_list(instance, "/api/cursors", warnings=warnings)
        result.counts.cursors = len(cursors)
        result.cursors = [_cursor(item) for item in cursors[:limit]]
    if kind in ("all", "loaders"):
        loaders = _optional_list(instance, "/api/loaders", warnings=warnings)
        result.counts.loaders = len(loaders)
        result.loaders = [_loader(item) for item in loaders[:limit]]
    if kind in ("all", "connections"):
        connections = _optional_list(instance, "/api/connections", warnings=warnings)
        result.counts.connections = len(connections)
        result.connections = [_connection(item) for item in connections[:limit]]
    if kind in ("all", "locks"):
        locks = _optional_list(instance, "/api/locks", warnings=warnings)
        result.counts.locks = len(locks)
        result.locks = [_lock(item) for item in locks[:limit]]

    result.warnings = warnings
    return result


async def list_timebase_activity(
    runtime: TimeBaseRuntime,
    *,
    instance_key: str | None = None,
    kind: ActivityKind = "all",
    limit: int = 50,
) -> TimeBaseActivityList:
    return await _run_monitor_operation(
        runtime,
        lambda instance: _activity_list_sync(instance, kind=kind, limit=limit),
        instance_key=instance_key,
    )


def _activity_detail_sync(
    instance: TimeBaseInstanceRuntime,
    *,
    kind: DetailKind,
    id: str,
    include_instruments: bool,
    instrument_offset: int,
    instrument_limit: int,
    instrument_filter: str | None,
) -> TimeBaseActivityDetail:
    warnings: list[str] = []
    instruments = None
    sanitized_id = quote_path_segment(id)

    if kind == "cursor":
        detail = _required_dict(instance, f"/api/cursors/{sanitized_id}")
        if include_instruments:
            instruments = _instruments(
                instance,
                f"/api/cursors/{sanitized_id}/instruments",
                offset=instrument_offset,
                limit=instrument_limit,
                filter_value=instrument_filter,
            )
    elif kind == "loader":
        detail = _required_dict(instance, f"/api/loaders/{sanitized_id}")
        if include_instruments:
            instruments = _instruments(
                instance,
                f"/api/loaders/{sanitized_id}/instruments",
                offset=instrument_offset,
                limit=instrument_limit,
                filter_value=instrument_filter,
            )
    elif kind == "connection":
        detail = _required_dict(instance, f"/api/connections/{sanitized_id}")
    else:
        detail = _find_lock(
            _optional_list(instance, "/api/locks", warnings=warnings), id
        )
        if detail is None:
            raise TimeBaseOperationError(f"Lock not found: {id}")

    return TimeBaseActivityDetail(
        instance_key=instance.key,
        kind=kind,
        detail=detail,
        instruments=instruments,
        warnings=warnings,
    )


async def get_timebase_activity_detail(
    runtime: TimeBaseRuntime,
    *,
    instance_key: str | None = None,
    kind: DetailKind,
    id: str,
    include_instruments: bool = False,
    instrument_offset: int = 0,
    instrument_limit: int = 50,
    instrument_filter: str | None = None,
) -> TimeBaseActivityDetail:
    return await _run_monitor_operation(
        runtime,
        lambda instance: _activity_detail_sync(
            instance,
            kind=kind,
            id=id,
            include_instruments=include_instruments,
            instrument_offset=instrument_offset,
            instrument_limit=instrument_limit,
            instrument_filter=instrument_filter,
        ),
        instance_key=instance_key,
    )


def _optional_list(
    instance: TimeBaseInstanceRuntime,
    endpoint: str,
    *,
    warnings: list[str],
) -> list[dict[str, Any]]:
    try:
        response = timebase_http_request(instance, endpoint)
        _raise_for_required_response(response, endpoint=endpoint)
        return response_json_list(
            response,
            what=endpoint,
            error_factory=TimeBaseOperationError,
        )
    except Exception as exc:
        warnings.append(f"{endpoint} unavailable: {exc}")
        return []


def _instruments(
    instance: TimeBaseInstanceRuntime,
    endpoint: str,
    *,
    offset: int,
    limit: int,
    filter_value: str | None,
) -> dict[str, Any]:
    params = {"offset": str(offset), "limit": str(limit)}
    if filter_value:
        params["filter"] = filter_value
    return _required_dict(instance, endpoint + "?" + urlencode(params))


def _find_lock(locks: list[dict[str, Any]], id: str) -> dict[str, Any] | None:
    for lock in locks:
        if (
            str(lock.get("id")) == id
            or lock.get("guid") == id
            or lock.get("clientId") == id
        ):
            return lock
    return None


def _license_summary(payload: dict[str, Any]) -> TimeBaseLicenseSummary:
    return TimeBaseLicenseSummary(
        valid=_bool(payload.get("valid")),
        valid_until=_str(payload.get("validUntil")),
        expiration_time=_str(payload.get("expirationTime")),
        days_valid=_int(payload.get("daysValid")),
        last_validate_time=_str(payload.get("lastValidateTime")),
        error=_str(payload.get("error")),
    )


def _runtime_summary(payload: dict[str, Any]) -> TimeBaseRuntimeSummary:
    props_value = payload.get("systemProperties")
    props: dict[str, Any] = props_value if isinstance(props_value, dict) else {}
    return TimeBaseRuntimeSummary(
        timestamp=_int(payload.get("timestamp")),
        cpu_count=_int(payload.get("cpuCount")),
        max_memory_mb=_int(payload.get("maxMemoryMb")),
        used_memory_mb=_int(payload.get("usedMemoryMb")),
        current_memory_mb=_int(payload.get("currentMemoryMb")),
        available_memory_mb=_int(payload.get("availableMemoryMb")),
        os_name=_str(props.get("os.name")),
        os_version=_str(props.get("os.version")),
        os_arch=_str(props.get("os.arch")),
        java_name=_str(props.get("java.runtime.name") or props.get("java.vm.name")),
        java_version=_str(props.get("java.version")),
        java_vendor=_str(props.get("java.vendor")),
    )


def _security_summary(payload: dict[str, Any]) -> TimeBaseSecuritySummary:
    return TimeBaseSecuritySummary(
        enabled=_bool(payload.get("enabled")),
        controller_type=_str(payload.get("controllerType")),
    )


def _cursor(item: dict[str, Any]) -> TimeBaseCursorActivity:
    return TimeBaseCursorActivity(
        id=int(item.get("id", 0)),
        user=_str(item.get("user")),
        application=_str(item.get("application")),
        source_stream_keys=list(item.get("sourceStreamKeys") or []),
        open_time=_int(item.get("openTime")),
        total_messages=_int(item.get("totalNumMessages")),
        last_message_timestamp=_int(item.get("lastMessageTimestamp")),
        last_message_sys_time=_int(item.get("lastMessageSysTime")),
    )


def _loader(item: dict[str, Any]) -> TimeBaseLoaderActivity:
    return TimeBaseLoaderActivity(
        id=int(item.get("id", 0)),
        user=_str(item.get("user")),
        application=_str(item.get("application")),
        target_stream_key=_str(item.get("targetStreamKey")),
        open_time=_int(item.get("openTime")),
        total_messages=_int(item.get("totalNumMessages")),
        last_message_timestamp=_int(item.get("lastMessageTimestamp")),
        last_message_sys_time=_int(item.get("lastMessageSysTime")),
        progress=_float(item.get("progress")),
    )


def _connection(item: dict[str, Any]) -> TimeBaseConnectionActivity:
    return TimeBaseConnectionActivity(
        client_id=str(item.get("clientId", "")),
        application_id=_str(item.get("applicationId")),
        creation_time=_int(item.get("creationTime")),
        remote_address=_str(item.get("remoteAddress")),
        num_transport_channels=_int(item.get("numTransportChannels")),
        throughput=_int(item.get("throughput")),
        average_throughput=_float(item.get("averageThroughput")),
    )


def _lock(item: dict[str, Any]) -> TimeBaseLockActivity:
    return TimeBaseLockActivity(
        id=int(item.get("id", 0)),
        guid=_str(item.get("guid")),
        type=_str(item.get("type")),
        client_id=_str(item.get("clientId")),
        stream_key=_str(item.get("streamKey")),
        application=_str(item.get("application")),
        user=_str(item.get("user")),
        host=_str(item.get("host")),
    )


def _str(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _bool(value: object) -> bool | None:
    return value if isinstance(value, bool) else None


def _int(value: object) -> int | None:
    return value if isinstance(value, int) else None


def _float(value: object) -> float | None:
    return float(value) if isinstance(value, int | float) else None
