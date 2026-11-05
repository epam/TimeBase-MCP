from __future__ import annotations

from types import ModuleType, SimpleNamespace

import pytest

from tests.stubs import stub_instance
from timebase_mcp.clients.base import TimeBaseClient
from timebase_mcp.clients.native import community, enterprise
from timebase_mcp.clients.native.common import read_stream_infos, read_stream_symbols
from timebase_mcp.errors import StreamNotFoundError, TimeBaseOperationCancelledError

_ADAPTERS = [
    (enterprise.EnterpriseTimeBaseClient, enterprise, "dxapi"),
    (community.CommunityTimeBaseClient, community, "dxapi_ce"),
]


def query_parameter(name: str, kind: str, value: str) -> tuple[str, str, str]:
    return name, kind, value


class QueryCursor:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows
        self.index = -1
        self.closed = False

    def next(self) -> bool:
        self.index += 1
        return self.index < len(self.rows)

    def getMessage(self) -> SimpleNamespace:
        return SimpleNamespace(**self.rows[self.index])

    def close(self) -> None:
        self.closed = True


class QueryDb:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.cursor = QueryCursor(rows)
        self.calls: list[tuple[str, list[object] | None]] = []

    def executeQuery(
        self, query: str, *, params: list[object] | None = None
    ) -> QueryCursor:
        self.calls.append((query, params))
        return self.cursor


@pytest.mark.parametrize(("client_class", "module", "library_attribute"), _ADAPTERS)
@pytest.mark.parametrize("offset", [0, 2])
def test_catalog_adapters_project_metadata_and_keep_system_streams(
    monkeypatch: pytest.MonkeyPatch,
    client_class: type[TimeBaseClient],
    module: ModuleType,
    library_attribute: str,
    offset: int,
) -> None:
    db = QueryDb(
        [
            {
                "total": 5,
                "keys": ["z", "metrics#", "#events"],
                "descriptions": ["z desc", None, "events"],
            },
        ]
    )
    client = client_class(stub_instance())
    library = SimpleNamespace(QueryParameter=query_parameter)
    monkeypatch.setattr(module, library_attribute, library)
    monkeypatch.setattr(client, "require_db", lambda: db)

    total, streams = client.list_stream_infos(offset, 3)

    assert total == 5
    assert [(s.key, s.description) for s in streams] == [
        ("z", "z desc"),
        ("metrics#", None),
        ("#events", "events"),
    ]
    assert db.calls == [
        (
            (
                "WITH streams() AS 'raw', raw[range(LO, min(HI, size(raw)))] AS 'selected' "
                "SELECT size(raw) AS 'total', selected.key AS 'keys', "
                "selected.description AS 'descriptions'"
            ),
            [("LO", "INTEGER", str(offset)), ("HI", "INTEGER", str(offset + 3))],
        )
    ]
    assert db.cursor.closed and client.rows_read == 1


@pytest.mark.parametrize(
    "rows",
    [
        [],
        [{}],
        [{"total": True, "keys": ["a"], "descriptions": [None]}],
        [{"total": -1}],
        [{"total": 1.0, "keys": ["a"], "descriptions": [None]}],
        [{"total": 1, "keys": [1], "descriptions": [None]}],
        [{"total": 1, "keys": ("a",), "descriptions": [None]}],
        [{"total": 1, "keys": ["a"], "descriptions": [3]}],
        [{"total": 1, "keys": ["a"], "descriptions": "desc"}],
        [{"total": 1, "keys": ["a"]}],
        [{"total": 1, "keys": ["a"], "descriptions": [None, None]}],
        [{"total": 2, "keys": ["a"], "descriptions": [None]}],
    ],
)
def test_invalid_catalog_rows_close_the_cursor(rows: list[dict[str, object]]) -> None:
    db = QueryDb(rows)
    with pytest.raises(ValueError):
        read_stream_infos(db, 0, 100, query_parameter, check_cancelled=lambda: None)
    assert db.cursor.closed


@pytest.mark.parametrize(
    ("total", "offset", "keys", "descriptions"),
    [
        (0, 0, None, None),
        (0, 0, [], []),
        (5, 5, None, None),
        (5, 8, [], []),
        (5, 3, ["z", "a"], [None, "a desc"]),
        (2, 0, ["z", "a"], [None, None]),
    ],
)
def test_catalog_empty_final_and_past_end_results(
    total: int,
    offset: int,
    keys: list[str] | None,
    descriptions: list[str | None] | None,
) -> None:
    db = QueryDb([{"total": total, "keys": keys, "descriptions": descriptions}])
    actual_total, streams = read_stream_infos(
        db, offset, 100, query_parameter, check_cancelled=lambda: None
    )
    assert actual_total == total
    assert [stream.key for stream in streams] == (keys or [])
    assert [stream.description for stream in streams] == (descriptions or [])
    assert db.cursor.closed


def test_catalog_cancellation_after_first_result_closes_cursor() -> None:
    db = QueryDb([{"total": 1, "keys": ["a"], "descriptions": [None]}])

    def cancelled() -> None:
        if db.cursor.index >= 0:
            raise TimeBaseOperationCancelledError("cancelled")

    with pytest.raises(TimeBaseOperationCancelledError):
        read_stream_infos(db, 0, 100, query_parameter, check_cancelled=cancelled)
    assert db.cursor.closed and db.cursor.index == 0


@pytest.mark.parametrize(("client_class", "module", "library_attribute"), _ADAPTERS)
@pytest.mark.parametrize("offset", [0, 2])
def test_adapters_bind_stream_keys_and_limit_symbols(
    monkeypatch: pytest.MonkeyPatch,
    client_class: type[TimeBaseClient],
    module: ModuleType,
    library_attribute: str,
    offset: int,
) -> None:
    key = "odd'\\stream"
    db = QueryDb([{"total": 4, "symbols": ["Z", "AA"]}])
    client = client_class(stub_instance())
    library = SimpleNamespace(QueryParameter=query_parameter)
    monkeypatch.setattr(module, library_attribute, library)
    monkeypatch.setattr(client, "require_db", lambda: db)

    assert client.list_stream_symbols(key, offset, 2) == (4, ["Z", "AA"])
    assert db.calls == [
        (
            (
                "WITH symbols(SK) AS 'raw' SELECT size(raw) AS 'total', "
                "sort(raw)[range(LO, min(HI, size(raw)))] AS 'symbols'"
            ),
            [
                ("SK", "VARCHAR", key),
                ("LO", "INTEGER", str(offset)),
                ("HI", "INTEGER", str(offset + 2)),
            ],
        )
    ]
    assert db.cursor.closed and client.rows_read == 1


def test_empty_symbols_and_missing_stream_are_distinct_and_close_the_cursor() -> None:
    empty = QueryDb([{"total": 0}])
    assert read_stream_symbols(
        empty, "empty", 0, 100, query_parameter, check_cancelled=lambda: None
    ) == (0, [])
    assert empty.cursor.closed
    missing = QueryDb([{}])
    with pytest.raises(StreamNotFoundError, match="missing"):
        read_stream_symbols(
            missing, "missing", 0, 100, query_parameter, check_cancelled=lambda: None
        )
    assert missing.cursor.closed


@pytest.mark.parametrize(
    ("offset", "symbols"),
    [(3, ["Z", "AA"]), (5, None), (8, [])],
)
def test_final_and_past_end_symbol_results(
    offset: int, symbols: list[str] | None
) -> None:
    db = QueryDb([{"total": 5, "symbols": symbols}])
    assert read_stream_symbols(
        db, "bars", offset, 100, query_parameter, check_cancelled=lambda: None
    ) == (5, symbols or [])
    assert db.cursor.closed


@pytest.mark.parametrize(
    "rows",
    [
        [],
        [{"total": True, "symbols": ["A"]}],
        [{"total": -1}],
        [{"total": 1.0, "symbols": ["A"]}],
        [{"total": 1, "symbols": [12]}],
        [{"total": 1, "symbols": ("A",)}],
        [{"total": 1, "symbols": "A"}],
        [{"total": 2, "symbols": ["A"]}],
        [{"total": 1, "symbols": ["A", "B"]}],
    ],
)
def test_bad_symbol_results_are_rejected_and_cursor_is_closed(
    rows: list[dict[str, object]],
) -> None:
    db = QueryDb(rows)
    with pytest.raises(ValueError):
        read_stream_symbols(
            db, "bars", 0, 100, query_parameter, check_cancelled=lambda: None
        )
    assert db.cursor.closed


def test_symbol_cancellation_after_first_result_closes_cursor() -> None:
    db = QueryDb([{"total": 1, "symbols": ["A"]}])

    def check_cancelled() -> None:
        if db.cursor.index >= 0:
            raise TimeBaseOperationCancelledError("cancelled")

    with pytest.raises(TimeBaseOperationCancelledError):
        read_stream_symbols(
            db, "bars", 0, 100, query_parameter, check_cancelled=check_cancelled
        )
    assert db.cursor.closed and db.cursor.index == 0


@pytest.mark.parametrize(
    ("offset", "limit"),
    [(-1, 1), (0, 0), (0, 501), (True, 1), (0, True), (2**31 - 1, 1)],
)
@pytest.mark.parametrize("symbols", [False, True], ids=["streams", "symbols"])
def test_bounds_are_validated_before_executing(
    offset: int, limit: int, symbols: bool
) -> None:
    db = QueryDb([])
    with pytest.raises(ValueError, match="bounds"):
        if symbols:
            read_stream_symbols(
                db, "bars", offset, limit, query_parameter, check_cancelled=lambda: None
            )
        else:
            read_stream_infos(
                db, offset, limit, query_parameter, check_cancelled=lambda: None
            )
    assert db.calls == []
