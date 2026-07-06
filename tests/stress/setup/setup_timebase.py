from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import dxapi_ce

BAR_MESSAGE_TYPE = "com.epam.deltix.timebase.messages.BarMessage"
BAR_INSTRUMENT_TYPE = "EQUITY"
EXCHANGE_ID = "NYSE"

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
COMMENT 'mcp stress bars'
""".strip()


@dataclass(frozen=True, slots=True)
class Bar:
    symbol: str
    timestamp: datetime
    open_price: float
    close_price: float
    high_price: float
    low_price: float
    volume: float


def main() -> int:
    timebase_url = os.getenv("TIMEBASE_URL", "dxtick://timebase:8011")
    stream_key = os.getenv("STRESS_STREAM_KEY", "mcp_stress_bars")
    rows = _int_env("STRESS_STREAM_ROWS", 10_000)
    symbols = _symbols_env("STRESS_STREAM_SYMBOLS")

    seed_stream(
        timebase_url=timebase_url, stream_key=stream_key, rows=rows, symbols=symbols
    )
    print(f"Seeded {rows} rows into TimeBase stream {stream_key!r}.")
    return 0


def seed_stream(
    *,
    timebase_url: str,
    stream_key: str,
    rows: int,
    symbols: list[str],
) -> None:
    db = dxapi_ce.TickDb.createFromUrl(timebase_url)
    db.open(False)
    try:
        execute_ddl(db, f'DROP STREAM IF EXISTS "{stream_key}"')
        execute_ddl(db, STREAM_DDL_TEMPLATE.format(stream_key=stream_key))

        stream = db.getStream(stream_key)
        if stream is None:
            raise RuntimeError(f"Expected stream {stream_key!r} to exist after DDL.")

        loader = stream.createLoader(dxapi_ce.LoadingOptions())
        try:
            for index, bar in enumerate(
                generate_bars(rows=rows, symbols=symbols), start=1
            ):
                message = dxapi_ce.InstrumentMessage()
                setattr(message, "typeName", BAR_MESSAGE_TYPE)
                setattr(message, "instrumentType", BAR_INSTRUMENT_TYPE)
                setattr(message, "symbol", bar.symbol)
                setattr(message, "timestamp", to_epoch_nanos(bar.timestamp))
                setattr(message, "originalTimestamp", 0)
                setattr(message, "currencyCode", 999)
                setattr(message, "exchangeId", EXCHANGE_ID)
                setattr(message, "open", bar.open_price)
                setattr(message, "close", bar.close_price)
                setattr(message, "high", bar.high_price)
                setattr(message, "low", bar.low_price)
                setattr(message, "volume", bar.volume)
                loader.send(message)
                if index % 1000 == 0:
                    print(f"Seeded {index} rows...")
        finally:
            loader.close()
    finally:
        db.close()


def generate_bars(*, rows: int, symbols: list[str]) -> Iterator[Bar]:
    start = datetime(2024, 1, 2, 14, 30, tzinfo=timezone.utc)
    for index in range(rows):
        symbol = symbols[index % len(symbols)]
        base = 100.0 + (index % 10_000) * 0.01 + (index % len(symbols)) * 7.5
        close = base + ((index % 11) - 5) * 0.03
        yield (
            Bar(
                symbol=symbol,
                timestamp=start + timedelta(seconds=index),
                open_price=base,
                close_price=close,
                high_price=max(base, close) + 0.25,
                low_price=min(base, close) - 0.25,
                volume=500.0 + (index % 250),
            )
        )


def execute_ddl(db, query: str) -> None:
    with db.tryExecuteQuery(query) as cursor:
        while cursor.next():
            pass


def to_epoch_nanos(value: datetime) -> int:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return int(value.timestamp() * 1_000_000_000)


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(value, 1)


def _symbols_env(name: str) -> list[str]:
    raw = os.getenv(name, "AAPL,MSFT,NVDA,GOOG,AMZN,META,TSLA,IBM")
    symbols = [symbol.strip() for symbol in raw.split(",") if symbol.strip()]
    return symbols or ["AAPL"]


if __name__ == "__main__":
    raise SystemExit(main())
