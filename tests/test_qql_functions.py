from typing import Any

from timebase_mcp.clients.base import TimeBaseClient
from timebase_mcp.instance import TimeBaseInstanceConfig
from timebase_mcp.qql_functions import normalize_qql_functions


class StubQQLFunctionsClient(TimeBaseClient):
    def __init__(self, messages_by_query: dict[str, list[dict[str, Any]]]) -> None:
        super().__init__(TimeBaseInstanceConfig(tb_url="dxtick://localhost:8011"))
        self.messages_by_query = messages_by_query
        self.executed_queries: list[str] = []

    def open(self) -> object:
        return object()

    def close(self) -> None:
        return None

    def _require_db(self) -> object:
        return object()

    def get_stream(self, stream_key: str) -> object:
        raise NotImplementedError

    def _get_stream_schema_text(self, stream: object) -> str:
        raise NotImplementedError

    def _list_stream_symbols(self, stream: object) -> list[str]:
        raise NotImplementedError

    def _get_stream_time_range_ms(self, stream: object) -> list[int] | None:
        raise NotImplementedError

    def _list_stream_spaces(self, stream: object) -> list[str] | None:
        raise NotImplementedError

    def _get_stream_space_time_range_ms(
        self,
        stream: object,
        space: str,
    ) -> list[int] | None:
        raise NotImplementedError

    def _read_stream_messages(
        self,
        stream: object,
        reverse: bool,
        count: int,
        space: str | None,
    ) -> list[dict[str, Any]]:
        raise NotImplementedError

    def _read_query_messages(self, query_text: str, limit: int) -> list[dict[str, Any]]:
        self.executed_queries.append(query_text)
        return self.messages_by_query[query_text]

    def _compile_query_tokens(self, query_text: str) -> list[Any]:
        raise NotImplementedError


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
    client = StubQQLFunctionsClient(
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

    result = client.list_qql_functions("stateless")

    assert client.executed_queries == ["SELECT stateless_functions() AS FUNCS"]
    assert [function.id for function in result.stateless] == ["ABS"]
    assert result.stateless[0].signatures == ["ABS(x: FLOAT64) -> FLOAT64?"]
    assert result.stateful == []
    assert result.function_count == 1
    assert result.overload_count == 1


def test_list_qql_functions_filters_by_function_id_server_side() -> None:
    query = "SELECT f AS FUNCS ARRAY JOIN stateful_functions() AS f WHERE f.id == 'SUM'"
    client = StubQQLFunctionsClient(
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

    result = client.list_qql_functions("stateful", function_id="SUM")

    assert client.executed_queries == [query]
    assert result.stateless == []
    assert result.stateful[0].id == "SUM"


def test_list_qql_functions_escapes_function_id_filter() -> None:
    query = (
        "SELECT f AS FUNCS ARRAY JOIN stateless_functions() AS f WHERE f.id == 'O''HLC'"
    )
    client = StubQQLFunctionsClient({query: []})

    result = client.list_qql_functions("stateless", function_id="O'HLC")

    assert client.executed_queries == [query]
    assert result.function_count == 0
    assert result.overload_count == 0
