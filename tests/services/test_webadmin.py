from __future__ import annotations

import pytest

from timebase_mcp.config.settings import MCPSettings
from timebase_mcp.errors import TimeBaseOperationError
from timebase_mcp.runtime.state import build_runtime
from timebase_mcp.services import webadmin


@pytest.mark.anyio
@pytest.mark.parametrize("identifier", [".", ".."])
@pytest.mark.parametrize(
    "operation",
    [
        webadmin.get_webadmin_view,
        webadmin.get_webadmin_topic_schema,
        webadmin.get_webadmin_background_task_status,
        webadmin.list_order_book_validation_issues,
    ],
)
async def test_dot_identifiers_fail_before_request(monkeypatch, operation, identifier):
    def unexpected_request(*args, **kwargs):
        pytest.fail("Dot identifier reached the WebAdmin client")

    monkeypatch.setattr(webadmin, "get_webadmin_json", unexpected_request)
    runtime = build_runtime(MCPSettings())
    try:
        with pytest.raises(TimeBaseOperationError, match="must not be '.' or '..'"):
            await operation(runtime, identifier)
    finally:
        await runtime.aclose()


@pytest.mark.anyio
async def test_list_views_is_sorted_and_capped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        webadmin,
        "get_webadmin_payload",
        lambda instance, endpoint: [
            {"id": f"view-{index:03d}"} for index in range(100, -1, -1)
        ],
    )
    runtime = build_runtime(MCPSettings())

    result = await webadmin.list_webadmin_views(runtime)

    assert result.returned_count == 100
    assert result.truncated is True
    assert result.items[0].id == "view-000"
    assert result.items[-1].id == "view-099"


@pytest.mark.anyio
async def test_validation_page_rejects_server_overreturn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        webadmin,
        "get_webadmin_json",
        lambda *args, **kwargs: {
            "issues": [{"message": "one"}, {"message": "two"}],
            "offset": 0,
            "rows": 1,
            "hasMore": False,
            "inlineOnly": False,
        },
    )
    with pytest.raises(TimeBaseOperationError, match="more validation issues"):
        await webadmin.list_order_book_validation_issues(
            build_runtime(MCPSettings()), "report", rows=1
        )


@pytest.mark.anyio
async def test_serialized_view_result_is_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        webadmin,
        "get_webadmin_payload",
        lambda *args: [{"id": str(i)} for i in range(100)],
    )
    monkeypatch.setattr(webadmin, "MAX_WEBADMIN_RESPONSE_BYTES", 2000)
    with pytest.raises(TimeBaseOperationError, match="serialized result limit"):
        await webadmin.list_webadmin_views(build_runtime(MCPSettings()))


@pytest.mark.anyio
async def test_invalid_response_does_not_echo_server_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        webadmin,
        "get_webadmin_payload",
        lambda *args: [{"id": {"access_token": "private-value"}}],
    )
    with pytest.raises(TimeBaseOperationError, match="invalid response shape") as exc:
        await webadmin.list_webadmin_views(build_runtime(MCPSettings()))
    assert "private-value" not in str(exc.value)


@pytest.mark.anyio
@pytest.mark.parametrize("payload", [{}, {"error": "private-value"}, {"issues": []}])
async def test_validation_page_rejects_missing_metadata(monkeypatch, payload):
    monkeypatch.setattr(webadmin, "get_webadmin_json", lambda *a, **kw: payload)
    with pytest.raises(TimeBaseOperationError, match="invalid response shape") as exc:
        await webadmin.list_order_book_validation_issues(
            build_runtime(MCPSettings()), "report"
        )
    assert "private-value" not in str(exc.value)


@pytest.mark.anyio
@pytest.mark.parametrize("include_issues", [True, False])
async def test_validation_page_accepts_empty_report(monkeypatch, include_issues):
    payload = {"offset": 0, "rows": 25, "hasMore": False, "inlineOnly": False}
    if include_issues:
        payload["issues"] = []
    monkeypatch.setattr(webadmin, "get_webadmin_json", lambda *a, **kw: payload)
    result = await webadmin.list_order_book_validation_issues(
        build_runtime(MCPSettings()), "report"
    )
    assert result.issues == []
    assert result.rows == 25
    assert result.has_more is False


@pytest.mark.anyio
@pytest.mark.parametrize(
    "operation,payload",
    [
        (webadmin.get_webadmin_topic_schema, {}),
        (webadmin.get_webadmin_topic_schema, {"error": "private-value"}),
        (webadmin.get_webadmin_topic_schema, {"types": []}),
        (webadmin.get_webadmin_topic_schema, {"all": []}),
        (webadmin.get_webadmin_topic_schema, {"types": None, "all": []}),
        (webadmin.get_webadmin_background_task_status, {}),
        (webadmin.get_webadmin_background_task_status, {"error": "private-value"}),
        (webadmin.get_webadmin_background_task_status, {"isFinished": False}),
        (webadmin.get_webadmin_background_task_status, {"progress": 0}),
        (
            webadmin.get_webadmin_background_task_status,
            {"isFinished": None, "progress": 0},
        ),
    ],
)
async def test_schema_and_task_reject_missing_required_fields(
    monkeypatch, operation, payload
):
    monkeypatch.setattr(webadmin, "get_webadmin_json", lambda *a, **kw: payload)
    with pytest.raises(TimeBaseOperationError, match="invalid response shape") as exc:
        await operation(build_runtime(MCPSettings()), "fixture")
    assert "private-value" not in str(exc.value)


@pytest.mark.anyio
async def test_empty_schema_and_no_background_task_remain_valid(monkeypatch):
    runtime = build_runtime(MCPSettings())
    monkeypatch.setattr(
        webadmin,
        "get_webadmin_json",
        lambda *a, **kw: {"types": [], "all": [], "futureField": True},
    )
    schema = await webadmin.get_webadmin_topic_schema(runtime, "topic")
    assert schema.model_dump() == {"types": [], "all": []}
    monkeypatch.setattr(
        webadmin,
        "get_webadmin_json",
        lambda *a, **kw: {
            "referToStream": "stream",
            "isFinished": False,
            "progress": 0,
            "status": "None",
            "name": None,
            "futureField": True,
        },
    )
    task = await webadmin.get_webadmin_background_task_status(runtime, "stream")
    assert task.is_finished is False
    assert task.progress == 0
    assert task.status == "None"
    assert task.name is None
