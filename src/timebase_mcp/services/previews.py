from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any


def format_messages_preview(
    header_lines: list[str],
    messages: list[dict[str, Any]],
    empty_text: str,
) -> str:
    if not messages:
        return "\n".join([*header_lines, "", empty_text])

    return "\n".join(
        [
            *header_lines,
            "",
            *[
                f"{index}. {json.dumps(message, default=json_default, sort_keys=True)}"
                for index, message in enumerate(messages, start=1)
            ],
        ]
    )


def json_default(value: Any) -> str:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()
    return str(value)
