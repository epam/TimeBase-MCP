from __future__ import annotations

import os

from locust import HttpUser, between, task
from typing_extensions import override

from mcp_streamable_http import StreamableHttpMcpClient


def _float_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


STREAM_KEY = os.getenv("LOCUST_STREAM_KEY", "mcp_stress_bars")
MCP_PATH = os.getenv("LOCUST_MCP_PATH", "/mcp")
WAIT_MIN = _float_env("LOCUST_WAIT_MIN_SECONDS", 0.2)
WAIT_MAX = _float_env("LOCUST_WAIT_MAX_SECONDS", 2.0)


class TimeBaseMcpUser(HttpUser):
    wait_time = between(WAIT_MIN, WAIT_MAX)

    @override
    def on_start(self) -> None:
        self.mcp = StreamableHttpMcpClient(self.client, path=MCP_PATH)
        self.mcp.initialize()

    @override
    def on_stop(self) -> None:
        self.mcp.close()

    @task(10)
    def get_server_configuration(self) -> None:
        self._call("get_server_configuration")

    @task(8)
    def list_timebase_instances(self) -> None:
        self._call("list_timebase_instances")

    @task(16)
    def list_streams(self) -> None:
        self._call("list_streams")

    @task(10)
    def get_stream_schema(self) -> None:
        self._call("get_stream_schema", {"stream_key": STREAM_KEY})

    @task(10)
    def get_stream_time_range(self) -> None:
        self._call("get_stream_time_range", {"stream_key": STREAM_KEY})

    @task(8)
    def get_stream_symbols(self) -> None:
        self._call("get_stream_symbols", {"stream_key": STREAM_KEY, "limit": 100})

    @task(5)
    def get_stream_messages_first(self) -> None:
        self._call("get_stream_messages", {"stream_key": STREAM_KEY, "count": 100})

    @task(5)
    def get_stream_messages_last(self) -> None:
        self._call(
            "get_stream_messages",
            {"stream_key": STREAM_KEY, "count": 100, "reverse": True},
        )

    @task(4)
    def execute_query_preview(self) -> None:
        self._call(
            "execute_query",
            {
                "query": f'select * from "{STREAM_KEY}"',
                "limit": 100,
            },
        )

    @task(2)
    def compile_query(self) -> None:
        self._call("compile_query", {"query": f'select * from "{STREAM_KEY}"'})

    @task(1)
    def list_qql_functions(self) -> None:
        self._call("list_qql_functions", {"kind": "stateless", "function_id": "SMA"})

    def _call(self, tool_name: str, arguments: dict | None = None) -> None:
        self.mcp.call_tool(tool_name, arguments or {})
