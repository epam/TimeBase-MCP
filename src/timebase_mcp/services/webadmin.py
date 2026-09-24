from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar
from urllib.parse import urlencode

from pydantic import BaseModel, ValidationError

from timebase_mcp.clients.http.urls import quote_path_segment
from timebase_mcp.clients.webadmin import (
    MAX_WEBADMIN_RESPONSE_BYTES,
    get_webadmin_json,
    get_webadmin_payload,
)
from timebase_mcp.errors import TimeBaseOperationError
from timebase_mcp.models.webadmin import (
    OrderBookValidationIssues,
    WebAdminAuthenticationInfo,
    WebAdminBackgroundTask,
    WebAdminInfo,
    WebAdminSchema,
    WebAdminTimeBaseInfo,
    WebAdminTopics,
    WebAdminView,
    WebAdminViews,
)
from timebase_mcp.runtime.instance import TimeBaseInstanceRuntime
from timebase_mcp.runtime.operations import run_http_with_runtime
from timebase_mcp.runtime.state import TimeBaseRuntime

MAX_LIST_ITEMS = 100
WebAdminResult = TypeVar("WebAdminResult", bound=BaseModel)


async def _run_webadmin(
    runtime: TimeBaseRuntime,
    operation: Callable[[TimeBaseInstanceRuntime], WebAdminResult],
    *,
    instance_key: str | None = None,
) -> WebAdminResult:
    def bounded(instance: TimeBaseInstanceRuntime) -> WebAdminResult:
        try:
            result = operation(instance)
        except (ValidationError, TypeError) as exc:
            raise TimeBaseOperationError(
                "WebAdmin returned an invalid response shape."
            ) from exc
        if len(result.model_dump_json().encode()) > MAX_WEBADMIN_RESPONSE_BYTES:
            raise TimeBaseOperationError(
                "WebAdmin result exceeded the 128 KiB serialized result limit."
            )
        return result

    return await run_http_with_runtime(runtime, bounded, instance_key=instance_key)


def _webadmin_info(instance: TimeBaseInstanceRuntime) -> WebAdminInfo:
    version = get_webadmin_json(instance, "/api/v0/v", authenticated=False)
    auth = get_webadmin_json(instance, "/api/v0/authInfo", authenticated=False)
    timebase = version.get("timebase")

    return WebAdminInfo(
        instance_key=instance.key,
        url=instance.config.webadmin.url or "",
        name=version.get("name") if isinstance(version.get("name"), str) else None,
        version=(
            version.get("version") if isinstance(version.get("version"), str) else None
        ),
        timestamp=(
            version.get("timestamp")
            if isinstance(version.get("timestamp"), int)
            else None
        ),
        authentication_enabled=(
            version.get("authentication")
            if isinstance(version.get("authentication"), bool)
            else None
        ),
        timebase=(
            WebAdminTimeBaseInfo.model_validate(timebase)
            if isinstance(timebase, dict)
            else None
        ),
        authentication=WebAdminAuthenticationInfo.model_validate(auth),
    )


async def get_webadmin_info(
    runtime: TimeBaseRuntime,
    *,
    instance_key: str | None = None,
) -> WebAdminInfo:
    return await _run_webadmin(
        runtime,
        _webadmin_info,
        instance_key=instance_key,
    )


def _list_views(instance: TimeBaseInstanceRuntime) -> WebAdminViews:
    payload = get_webadmin_payload(instance, "/api/v0/timebase/views")
    if not isinstance(payload, list):
        raise TypeError("WebAdmin views response must be a JSON array.")
    views = sorted(
        (WebAdminView.model_validate(item) for item in payload),
        key=lambda view: view.id,
    )
    return WebAdminViews(
        items=views[:MAX_LIST_ITEMS],
        returned_count=min(len(views), MAX_LIST_ITEMS),
        truncated=len(views) > MAX_LIST_ITEMS,
    )


async def list_webadmin_views(
    runtime: TimeBaseRuntime,
    *,
    instance_key: str | None = None,
) -> WebAdminViews:
    return await _run_webadmin(runtime, _list_views, instance_key=instance_key)


async def get_webadmin_view(
    runtime: TimeBaseRuntime,
    view_id: str,
    *,
    instance_key: str | None = None,
) -> WebAdminView:
    return await _run_webadmin(
        runtime,
        lambda instance: WebAdminView.model_validate(
            get_webadmin_json(
                instance,
                f"/api/v0/timebase/views/{quote_path_segment(view_id)}",
            )
        ),
        instance_key=instance_key,
    )


def _list_topics(instance: TimeBaseInstanceRuntime) -> WebAdminTopics:
    payload = get_webadmin_payload(instance, "/api/v0/topics")
    if not isinstance(payload, list) or not all(
        isinstance(item, str) for item in payload
    ):
        raise TypeError("WebAdmin topics response must be a JSON string array.")
    topics = sorted(payload)
    return WebAdminTopics(
        items=topics[:MAX_LIST_ITEMS],
        returned_count=min(len(topics), MAX_LIST_ITEMS),
        truncated=len(topics) > MAX_LIST_ITEMS,
    )


async def list_webadmin_topics(
    runtime: TimeBaseRuntime,
    *,
    instance_key: str | None = None,
) -> WebAdminTopics:
    return await _run_webadmin(runtime, _list_topics, instance_key=instance_key)


async def get_webadmin_topic_schema(
    runtime: TimeBaseRuntime,
    topic_id: str,
    *,
    instance_key: str | None = None,
) -> WebAdminSchema:
    return await _run_webadmin(
        runtime,
        lambda instance: WebAdminSchema.model_validate(
            get_webadmin_json(
                instance,
                f"/api/v0/topics/{quote_path_segment(topic_id)}/schema",
            )
        ),
        instance_key=instance_key,
    )


async def get_webadmin_background_task_status(
    runtime: TimeBaseRuntime,
    stream_id: str,
    *,
    instance_key: str | None = None,
) -> WebAdminBackgroundTask:
    return await _run_webadmin(
        runtime,
        lambda instance: WebAdminBackgroundTask.model_validate(
            get_webadmin_json(
                instance,
                f"/api/v0/{quote_path_segment(stream_id)}/options/backgroundTask",
            )
        ),
        instance_key=instance_key,
    )


async def list_order_book_validation_issues(
    runtime: TimeBaseRuntime,
    report_id: str,
    *,
    offset: int = 0,
    rows: int = 25,
    from_time: str | None = None,
    to_time: str | None = None,
    severity: str | None = None,
    source_name: str | None = None,
    symbol: str | None = None,
    instance_key: str | None = None,
) -> OrderBookValidationIssues:
    if offset < 0 or not 1 <= rows <= 25:
        raise TimeBaseOperationError(
            "Validation issues require offset >= 0 and 1 <= rows <= 25."
        )
    query = urlencode(
        {
            key: value
            for key, value in {
                "offset": offset,
                "rows": rows,
                "from": from_time,
                "to": to_time,
                "severity": severity,
                "sourceName": source_name,
                "symbol": symbol,
            }.items()
            if value is not None
        }
    )
    result = await _run_webadmin(
        runtime,
        lambda instance: OrderBookValidationIssues.model_validate(
            get_webadmin_json(
                instance,
                "/api/v0/orderBookValidation/report/"
                f"{quote_path_segment(report_id)}/issues?{query}",
            )
        ),
        instance_key=instance_key,
    )
    if len(result.issues) > rows:
        raise TimeBaseOperationError(
            "WebAdmin returned more validation issues than requested."
        )
    return result
