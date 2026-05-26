from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from importlib import import_module
from time import monotonic, sleep
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

from timebase_mcp.clients.factory import create_timebase_client, get_detected_edition
from timebase_mcp.config import Edition
from timebase_mcp.config import MCPSettings


INTEGRATION_STREAM_KEY = "mcp_integration_bars"
BAR_MESSAGE_TYPE = "com.epam.deltix.timebase.messages.BarMessage"
BAR_INSTRUMENT_TYPE = "EQUITY"
EXCHANGE_ID = "NYSE"
PING_TIMEOUT_SECONDS = 30

STREAM_DDL_TEMPLATE = """
CREATE DURABLE STREAM "{stream_key}" '{stream_key}' (
    CLASS "com.epam.deltix.timebase.messages.MarketMessage" 'Market Message' (
        STATIC "originalTimestamp" TIMESTAMP = NULL,
        STATIC "currencyCode" 'Currency Code' INTEGER = 999,
        STATIC "sequenceNumber" '' INTEGER = NULL,
        STATIC "sourceId" '' VARCHAR = NULL
    ) NOT INSTANTIABLE;
    CLASS "com.epam.deltix.timebase.messages.BarMessage" 'Bar Message' UNDER "com.epam.deltix.timebase.messages.MarketMessage" (
        STATIC "exchangeId" 'Exchange Code' VARCHAR = NULL,
        "close" 'Close' FLOAT DECIMAL,
        "open" 'Open' FLOAT DECIMAL RELATIVE TO "close",
        "high" 'High' FLOAT DECIMAL RELATIVE TO "close",
        "low" 'Low' FLOAT DECIMAL RELATIVE TO "close",
        "volume" 'Volume' FLOAT DECIMAL
    );
)
OPTIONS (FIXEDTYPE; PERIODICITY = '1I'; HIGHAVAILABILITY = TRUE)
COMMENT 'mcp integration bars'
""".strip()


@dataclass(frozen=True)
class SeedBar:
    symbol: str
    timestamp: datetime
    open_price: float
    close_price: float
    high_price: float
    low_price: float
    volume: float


SEEDED_BARS = (
    SeedBar(
        symbol="AAPL",
        timestamp=datetime(2024, 1, 2, 14, 30, tzinfo=timezone.utc),
        open_price=187.25,
        close_price=188.5,
        high_price=189.1,
        low_price=186.8,
        volume=1050.0,
    ),
    SeedBar(
        symbol="MSFT",
        timestamp=datetime(2024, 1, 2, 14, 31, tzinfo=timezone.utc),
        open_price=372.0,
        close_price=373.5,
        high_price=374.2,
        low_price=371.6,
        volume=980.0,
    ),
    SeedBar(
        symbol="AAPL",
        timestamp=datetime(2024, 1, 2, 14, 32, tzinfo=timezone.utc),
        open_price=188.6,
        close_price=189.0,
        high_price=189.4,
        low_price=188.2,
        volume=1115.0,
    ),
)


@dataclass(frozen=True)
class SeededStream:
    stream_key: str
    symbols: tuple[str, ...]
    first_timestamp: datetime
    last_timestamp: datetime


def wait_for_timebase(
    settings: MCPSettings,
    *,
    ping_url: str | None = None,
    timeout_seconds: float = PING_TIMEOUT_SECONDS,
) -> None:
    resolved_ping_url = ping_url or build_ping_url(settings.tb_url)
    deadline = monotonic() + timeout_seconds

    while monotonic() < deadline:
        try:
            with urlopen(resolved_ping_url, timeout=2) as response:
                if response.status == 200:
                    return
        except URLError:
            sleep(1)

    raise RuntimeError(
        f"TimeBase did not become ready at {resolved_ping_url!r} within {timeout_seconds} seconds. "
        "Set TIMEBASE_PING_URL if the server exposes a different readiness endpoint."
    )


def seed_bars_stream(
    settings: MCPSettings,
    stream_key: str = INTEGRATION_STREAM_KEY,
) -> SeededStream:
    module = _load_client_module(_resolve_integration_edition(settings))
    password = (
        settings.tb_password.get_secret_value()
        if settings.tb_password is not None
        else None
    )

    if settings.tb_username is None and password is None:
        db = module.TickDb.createFromUrl(settings.tb_url)
    else:
        assert settings.tb_username is not None
        assert password is not None
        db = module.TickDb.createFromUrl(
            settings.tb_url, settings.tb_username, password
        )

    db.open(False)
    try:
        _execute_ddl(db, f'DROP STREAM IF EXISTS "{stream_key}"')
        _execute_ddl(db, STREAM_DDL_TEMPLATE.format(stream_key=stream_key))

        stream = db.getStream(stream_key)
        if stream is None:
            raise RuntimeError(
                f"Expected stream {stream_key!r} to exist after DDL execution."
            )

        loader = stream.createLoader(module.LoadingOptions())
        try:
            for bar in SEEDED_BARS:
                message = module.InstrumentMessage()
                setattr(message, "typeName", BAR_MESSAGE_TYPE)
                setattr(message, "instrumentType", BAR_INSTRUMENT_TYPE)
                setattr(message, "symbol", bar.symbol)
                setattr(message, "timestamp", _to_epoch_nanos(bar.timestamp))
                setattr(message, "originalTimestamp", 0)
                setattr(message, "currencyCode", 999)
                setattr(message, "exchangeId", EXCHANGE_ID)
                setattr(message, "open", bar.open_price)
                setattr(message, "close", bar.close_price)
                setattr(message, "high", bar.high_price)
                setattr(message, "low", bar.low_price)
                setattr(message, "volume", bar.volume)
                loader.send(message)
        finally:
            loader.close()
    finally:
        db.close()

    return SeededStream(
        stream_key=stream_key,
        symbols=tuple(sorted({bar.symbol for bar in SEEDED_BARS})),
        first_timestamp=SEEDED_BARS[0].timestamp,
        last_timestamp=SEEDED_BARS[-1].timestamp,
    )


def build_ping_url(timebase_url: str) -> str:
    if "://" not in timebase_url:
        raise ValueError(f"Unsupported TimeBase URL: {timebase_url!r}")

    _, remainder = timebase_url.split("://", maxsplit=1)
    host_port = remainder.rstrip("/")
    if not host_port:
        raise ValueError(f"Unsupported TimeBase URL: {timebase_url!r}")

    return f"http://{host_port}/tb/ping"


def _execute_ddl(db: Any, query: str) -> None:
    with db.tryExecuteQuery(query) as cursor:
        while cursor.next():
            pass


def _resolve_integration_edition(settings: MCPSettings) -> Edition:
    detected_edition = get_detected_edition(settings)
    if detected_edition is not None:
        return detected_edition

    client = create_timebase_client(settings)
    try:
        if settings.detected_edition is None:
            client.open()
        detected_edition = settings.detected_edition
    finally:
        client.close()

    if detected_edition is None:
        raise RuntimeError("Failed to detect the TimeBase client edition.")

    return detected_edition


def _load_client_module(edition: Edition) -> Any:
    if edition == "community":
        return import_module("dxapi_ce")
    if edition == "enterprise":
        return import_module("dxapi")

    raise ValueError(
        f"Unsupported TimeBase edition for integration tests: {edition!r}."
    )


def _to_epoch_nanos(value: datetime) -> int:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return int(value.timestamp() * 1_000_000_000)
