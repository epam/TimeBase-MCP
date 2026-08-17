from __future__ import annotations

from datetime import datetime, timedelta, timezone

from timebase_mcp.services.previews import format_messages_preview, json_default


def test_format_messages_preview_empty_messages() -> None:
    text = format_messages_preview(
        header_lines=["Stream: bars", "Showing 0 of requested 10 first messages"],
        messages=[],
        empty_text="No messages found.",
    )

    assert text == (
        "Stream: bars\n"
        "Showing 0 of requested 10 first messages\n"
        "\n"
        "No messages found."
    )


def test_format_messages_preview_numbers_sorted_json_lines() -> None:
    text = format_messages_preview(
        header_lines=["Query: select 1"],
        messages=[{"b": 2, "a": 1}, {"z": True}],
        empty_text="No result rows.",
    )

    assert text == (
        "Query: select 1\n"
        "\n"
        '1. {"a": 1, "b": 2}\n'
        '2. {"z": true}'
    )


def test_json_default_naive_datetime_becomes_utc_iso() -> None:
    assert (
        json_default(datetime(2024, 1, 2, 3, 4, 5)) == "2024-01-02T03:04:05+00:00"
    )


def test_json_default_aware_datetime_converted_to_utc() -> None:
    eastern = timezone(timedelta(hours=-5))
    assert (
        json_default(datetime(2024, 1, 2, 3, 4, 5, tzinfo=eastern))
        == "2024-01-02T08:04:05+00:00"
    )


def test_json_default_non_datetime_uses_str() -> None:
    sentinel = object()
    assert json_default(sentinel) == str(sentinel)
    assert json_default(42) == "42"
