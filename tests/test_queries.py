from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import Any

import pytest
from typing_extensions import override

from timebase_mcp.clients.base import TimeBaseClient
from timebase_mcp.constants import DEFAULT_INSTANCE_KEY
from timebase_mcp.errors import ReadOnlyInstanceError, TimeBaseOperationCancelledError
from timebase_mcp.models.core import StreamInfo
from timebase_mcp.runtime.instance import (
    TimeBaseInstanceConfig,
    TimeBaseInstanceRuntime,
)
from timebase_mcp.services.qql_functions import normalize_qql_functions
from timebase_mcp.services.queries import execute_query, list_qql_functions


class StubQueryClient(TimeBaseClient):
    def __init__(
        self,
        messages_by_query: dict[str, list[dict[str, Any]]] | None = None,
        *,
        read_only: bool = False,
        tokens: list[Any] | None = None,
    ) -> None:
        super().__init__(
            TimeBaseInstanceRuntime(
                key=DEFAULT_INSTANCE_KEY,
                config=TimeBaseInstanceConfig(
                    tb_url="dxtick://localhost:8011",
                    read_only=read_only,
                ),
            )
        )
        self.messages_by_query = messages_by_query or {}
        self.tokens = tokens or []
        self.executed_queries: list[str] = []

    @override
    def open(self) -> object:
        return object()

    @override
    def close(self) -> None:
        return None

    @override
    def require_db(self) -> object:
        return object()

    @override
    def get_stream(self, stream_key: str) -> object:
        raise NotImplementedError

    @override
    def get_stream_schema_text(self, stream: object) -> str:
        raise NotImplementedError

    @override
    def list_stream_symbols(self, stream: object) -> list[str]:
        raise NotImplementedError

    @override
    def list_stream_infos(self) -> list[StreamInfo]:
        raise NotImplementedError

    @override
    def get_stream_time_range(
        self,
        stream_key: str,
        stream: object,
    ) -> tuple[datetime | None, datetime | None]:
        raise NotImplementedError

    @override
    def list_stream_spaces(self, stream: object) -> list[str] | None:
        raise NotImplementedError

    @override
    def get_stream_space_time_range(
        self,
        stream_key: str,
        stream: object,
        space: str,
    ) -> tuple[datetime | None, datetime | None]:
        raise NotImplementedError

    @override
    def read_stream_messages(
        self,
        stream: object,
        reverse: bool,
        count: int,
        space: str | None,
    ) -> list[dict[str, Any]]:
        raise NotImplementedError

    @override
    def read_query_messages(self, query_text: str, limit: int) -> list[dict[str, Any]]:
        self.executed_queries.append(query_text)
        return self.messages_by_query.get(query_text, [])

    @override
    def compile_query_tokens(self, query_text: str) -> list[Any]:
        return self.tokens


def test_normalize_qql_functions_groups_and_deduplicates_signatures() -> None:
    result = normalize_qql_functions(
        "stateless",
        [
            {
                "FUNCS": [
                    {
                        "id": "MAX",
                        "arguments": [
                            {
                                "name": "ARG0",
                                "dataType": {
                                    "baseName": "INTEGER",
                                    "encoding": "INT64",
                                    "isNullable": False,
                                },
                            },
                            {
                                "name": "ARG1",
                                "dataType": {
                                    "baseName": "INTEGER",
                                    "encoding": "INT64",
                                    "isNullable": False,
                                },
                            },
                        ],
                        "returnType": {
                            "baseName": "INTEGER",
                            "encoding": "INT64",
                            "isNullable": True,
                        },
                    },
                    {
                        "id": "MAX",
                        "arguments": [
                            {
                                "name": "ARG0",
                                "dataType": {
                                    "baseName": "INTEGER",
                                    "encoding": "INT64",
                                    "isNullable": False,
                                },
                            },
                            {
                                "name": "ARG1",
                                "dataType": {
                                    "baseName": "INTEGER",
                                    "encoding": "INT64",
                                    "isNullable": False,
                                },
                            },
                        ],
                        "returnType": {
                            "baseName": "INTEGER",
                            "encoding": "INT64",
                            "isNullable": True,
                        },
                    },
                    {
                        "id": "ABS",
                        "arguments": [
                            {
                                "name": "ARG0",
                                "dataType": {
                                    "baseName": "ARRAY",
                                    "elementType": {
                                        "baseName": "FLOAT",
                                        "encoding": "IEEE64",
                                        "isNullable": False,
                                    },
                                    "isNullable": False,
                                },
                            }
                        ],
                        "returnType": {
                            "baseName": "ARRAY",
                            "elementType": {
                                "baseName": "FLOAT",
                                "encoding": "IEEE64",
                                "isNullable": True,
                            },
                            "isNullable": True,
                        },
                    },
                ]
            }
        ],
    )

    assert [function.model_dump() for function in result] == [
        {
            "id": "ABS",
            "signatures": [
                "ABS(ARG0: ARRAY<FLOAT(IEEE64)>) -> ARRAY<FLOAT(IEEE64)?>?",
            ],
            "overload_count": 1,
        },
        {
            "id": "MAX",
            "signatures": [
                "MAX(ARG0: INTEGER(INT64), ARG1: INTEGER(INT64)) -> INTEGER(INT64)?",
            ],
            "overload_count": 1,
        },
    ]


def test_normalize_qql_functions_includes_stateful_init_defaults() -> None:
    result = normalize_qql_functions(
        "stateful",
        [
            {
                "FUNCS": [
                    {
                        "id": "SUM",
                        "initArguments": [
                            {
                                "name": "PERIOD",
                                "defaultValue": None,
                                "dataType": {
                                    "baseName": "INTEGER",
                                    "encoding": "INT32",
                                    "isNullable": False,
                                },
                            },
                            {
                                "name": "RESET",
                                "defaultValue": "true",
                                "dataType": {
                                    "baseName": "BOOLEAN",
                                    "isNullable": False,
                                },
                            },
                        ],
                        "arguments": [
                            {
                                "name": "ARG1",
                                "dataType": {
                                    "baseName": "FLOAT",
                                    "encoding": "DECIMAL64",
                                    "isNullable": False,
                                },
                            }
                        ],
                        "returnType": {
                            "baseName": "FLOAT",
                            "encoding": "DECIMAL64",
                            "isNullable": True,
                        },
                    }
                ]
            }
        ],
    )

    assert result[0].signatures == [
        "SUM{PERIOD: INTEGER(INT32), RESET: BOOLEAN = true}(ARG1: FLOAT(DECIMAL64)) -> FLOAT(DECIMAL64)?"
    ]


def test_normalize_qql_functions_preserves_unknown_encoding() -> None:
    result = normalize_qql_functions(
        "stateless",
        [
            {
                "FUNCS": {
                    "id": "CUSTOM",
                    "arguments": [
                        {
                            "name": "ARG0",
                            "dataType": {
                                "baseName": "FLOAT",
                                "encoding": "FUTURE_ENCODING",
                                "isNullable": False,
                            },
                        }
                    ],
                    "returnType": {
                        "baseName": "FLOAT",
                        "encoding": "FUTURE_ENCODING",
                        "isNullable": True,
                    },
                }
            }
        ],
    )

    assert result[0].signatures == [
        "CUSTOM(ARG0: FLOAT(FUTURE_ENCODING)) -> FLOAT(FUTURE_ENCODING)?"
    ]


def test_list_qql_functions_can_filter_by_kind() -> None:
    client = StubQueryClient(
        {
            "SELECT stateless_functions() AS FUNCS": [
                {
                    "FUNCS": {
                        "id": "ABS",
                        "argument_names": ["x"],
                        "argument_data_types": ["FLOAT64"],
                        "return_type": "FLOAT64?",
                    }
                }
            ],
        }
    )

    result = list_qql_functions(client, "stateless")

    assert client.executed_queries == ["SELECT stateless_functions() AS FUNCS"]
    assert [function.id for function in result.stateless] == ["ABS"]
    assert result.stateless[0].signatures == ["ABS(x: FLOAT64) -> FLOAT64?"]
    assert result.stateful == []
    assert result.function_count == 1
    assert result.overload_count == 1


def test_list_qql_functions_filters_by_function_id_server_side() -> None:
    query = "SELECT f AS FUNCS ARRAY JOIN stateful_functions() AS f WHERE f.id == 'SUM'"
    client = StubQueryClient(
        {
            query: [
                {
                    "FUNCS": {
                        "id": "SUM",
                        "arguments": [],
                        "initArguments": [],
                        "returnType": "FLOAT64?",
                    }
                }
            ],
        }
    )

    result = list_qql_functions(client, "stateful", function_id="SUM")

    assert client.executed_queries == [query]
    assert result.stateless == []
    assert result.stateful[0].id == "SUM"


@pytest.mark.parametrize(
    "function_id",
    ["MAX' OR '1'='1", "O'HLC", "math.abs", "1MAX", "A B", ""],
)
def test_list_qql_functions_rejects_non_identifier_function_id(
    function_id: str,
) -> None:
    client = StubQueryClient()

    with pytest.raises(ValueError, match="function_id must be"):
        list_qql_functions(client, "stateless", function_id=function_id)

    assert client.executed_queries == []


def test_list_qql_functions_raises_and_stops_when_cancelled() -> None:
    """A stop must not yield a truncated result presented as complete."""
    stateless_query = "SELECT stateless_functions() AS FUNCS"
    stateful_query = "SELECT stateful_functions() AS FUNCS"

    class CancellingClient(StubQueryClient):
        @override
        def read_query_messages(
            self, query_text: str, limit: int
        ) -> list[dict[str, Any]]:
            self.executed_queries.append(query_text)
            # Mimic a read loop that broke between rows: partial data, flag set.
            self.request_cancel()
            return []

    client = CancellingClient({stateless_query: [], stateful_query: []})

    with pytest.raises(TimeBaseOperationCancelledError):
        list_qql_functions(client, "all")

    # The second query must never be issued after a stop.
    assert client.executed_queries == [stateless_query]


def _keyword_token(query: str, keyword: str) -> object:
    """A KEYWORD token located where ``keyword`` appears, as the compiler reports it.

    ``location`` packs start line/column and end line/column, 16 bits per field.
    """
    line_number, line = next(
        (index, text)
        for index, text in enumerate(query.splitlines())
        if keyword in text
    )
    column = line.index(keyword)
    location = (
        (line_number << 48)
        | (column << 32)
        | (line_number << 16)
        | (column + len(keyword))
    )
    return SimpleNamespace(type="KEYWORD", location=location)


@pytest.mark.parametrize("keyword", ["SELECT", "select"])
def test_read_only_instance_allows_select_queries(keyword: str) -> None:
    query = f"{keyword} value FROM bars"
    client = StubQueryClient(read_only=True, tokens=[_keyword_token(query, keyword)])

    execute_query(client, query)

    assert client.executed_queries == [query]


def test_read_only_instance_allows_parenthesised_select() -> None:
    # Tokens before the leading keyword are skipped, so "(SELECT ...)" is a query.
    query = '(SELECT value FROM "bars")'
    client = StubQueryClient(
        read_only=True,
        tokens=[
            SimpleNamespace(type="PUNCTUATION", location=1),
            _keyword_token(query, "SELECT"),
        ],
    )

    execute_query(client, query)

    assert client.executed_queries == [query]


def test_read_only_instance_rejects_ddl() -> None:
    query = 'DROP STREAM "bars"'
    client = StubQueryClient(read_only=True, tokens=[_keyword_token(query, "DROP")])

    with pytest.raises(ReadOnlyInstanceError) as error_info:
        execute_query(client, query)

    assert "'DROP' statements are rejected" in str(error_info.value)
    assert client.executed_queries == []


def test_read_only_instance_rejects_ddl_hidden_behind_comments() -> None:
    # The TimeBase lexer skips comments, so the first token is the real statement.
    query = '/* SELECT */ -- SELECT\nCREATE DURABLE STREAM "bars"'
    client = StubQueryClient(read_only=True, tokens=[_keyword_token(query, "CREATE")])

    with pytest.raises(ReadOnlyInstanceError, match="'CREATE' statements are rejected"):
        execute_query(client, query)

    assert client.executed_queries == []


@pytest.mark.parametrize(
    "tokens",
    [
        pytest.param([], id="no-keyword"),
        pytest.param([SimpleNamespace(type="KEYWORD", location=None)], id="unreadable"),
    ],
)
def test_read_only_instance_rejects_unrecognized_statements(tokens: list[Any]) -> None:
    client = StubQueryClient(read_only=True, tokens=tokens)

    with pytest.raises(ReadOnlyInstanceError, match="This query is rejected"):
        execute_query(client, "SELECT value FROM bars")

    assert client.executed_queries == []


def test_writable_instance_runs_queries_without_classifying() -> None:
    query = 'DROP STREAM "bars"'
    client = StubQueryClient(tokens=[_keyword_token(query, "DROP")])

    execute_query(client, query)

    assert client.executed_queries == [query]
