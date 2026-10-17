"""Two-year multi-timeframe BTCUSDT library, plus the derivatives rows that accumulate from now.

Spot klines can be backfilled from the public Binance vision API. Open interest
and the taker ratio are appended by DerivativesFeed because the public history
is short. Funding can be backfilled.
"""
import json
import sqlite3
import time
import urllib.request
from typing import Iterable, List, Optional

INTERVAL_MS = {
    "1m": 60_000, "5m": 300_000, "15m": 900_000, "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000,
}
KLINE_URL = "https://data-api.binance.vision/api/v3/klines?symbol={symbol}&interval={interval}&startTime={start}&endTime={end}&limit=1000"
FUNDING_URL = "https://fapi.binance.com/fapi/v1/fundingRate?symbol={symbol}&startTime={start}&limit=1000"
TWO_YEARS_MS = 730 * 24 * 3600 * 1000


def bar_from_kline(row) -> dict:
    return {
        "time": int(row[0]), "open": float(row[1]), "high": float(row[2]), "low": float(row[3]),
        "close": float(row[4]), "volume": float(row[5]), "close_time": int(row[6]),
        "taker_buy_base": float(row[9]), "is_closed": True,
    }


def get_json(url: str, attempts: int = 5):
    last = None
    for attempt in range(attempts):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "cryptog-v2"})
            with urllib.request.urlopen(request, timeout=20) as response:
                return json.loads(response.read().decode())
        except Exception as exc:
            last = exc
            time.sleep(min(8, 0.5 * (2 ** attempt)))
    raise last


class ResearchStore:
    def __init__(self, path: str):
        self.path = path
        self.db = sqlite3.connect(path, check_same_thread=False, timeout=30)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS klines(
            symbol TEXT NOT NULL, interval TEXT NOT NULL, open_time INTEGER NOT NULL,
            open REAL NOT NULL, high REAL NOT NULL, low REAL NOT NULL, close REAL NOT NULL,
            volume REAL NOT NULL, close_time INTEGER NOT NULL, taker_buy_base REAL NOT NULL,
            PRIMARY KEY(symbol, interval, open_time));
        CREATE TABLE IF NOT EXISTS funding_rates(
            symbol TEXT NOT NULL, funding_time INTEGER NOT NULL, rate REAL NOT NULL,
            PRIMARY KEY(symbol, funding_time));
        CREATE TABLE IF NOT EXISTS open_interest(
            symbol TEXT NOT NULL, time INTEGER NOT NULL, oi REAL NOT NULL,
            PRIMARY KEY(symbol, time));
        CREATE TABLE IF NOT EXISTS taker_ratio(
            symbol TEXT NOT NULL, time INTEGER NOT NULL, sell_buy_ratio REAL NOT NULL,
            PRIMARY KEY(symbol, time));
        """)
        self.db.commit()

    def close(self):
        self.db.close()

    def upsert_klines(self, symbol: str, interval: str, bars: Iterable[dict]) -> int:
        rows = [(symbol, interval, int(b["time"]), float(b["open"]), float(b["high"]), float(b["low"]),
                 float(b["close"]), float(b["volume"]), int(b["close_time"]), float(b.get("taker_buy_base") or 0))
                for b in bars]
        if not rows:
            return 0
        with self.db:
            self.db.executemany("""INSERT INTO klines VALUES(?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(symbol, interval, open_time) DO UPDATE SET
                open=excluded.open, high=excluded.high, low=excluded.low, close=excluded.close,
                volume=excluded.volume, close_time=excluded.close_time, taker_buy_base=excluded.taker_buy_base""", rows)
        return len(rows)

    def upsert_funding(self, symbol: str, rows: Iterable[dict]) -> int:
        payload = [(symbol, int(r["time"]), float(r["rate"])) for r in rows]
        if not payload:
            return 0
        with self.db:
            self.db.executemany("""INSERT INTO funding_rates VALUES(?,?,?)
                ON CONFLICT(symbol, funding_time) DO UPDATE SET rate=excluded.rate""", payload)
        return len(payload)

    def upsert_open_interest(self, symbol: str, rows: Iterable[dict]) -> int:
        payload = [(symbol, int(r["time"]), float(r["oi"])) for r in rows]
        if not payload:
            return 0
        with self.db:
            self.db.executemany("""INSERT INTO open_interest VALUES(?,?,?)
                ON CONFLICT(symbol, time) DO UPDATE SET oi=excluded.oi""", payload)
        return len(payload)

    def upsert_taker(self, symbol: str, rows: Iterable[dict]) -> int:
        payload = [(symbol, int(r["time"]), float(r["sell_buy_ratio"])) for r in rows]
        if not payload:
            return 0
        with self.db:
            self.db.executemany("""INSERT INTO taker_ratio VALUES(?,?,?)
                ON CONFLICT(symbol, time) DO UPDATE SET sell_buy_ratio=excluded.sell_buy_ratio""", payload)
        return len(payload)

    def max_open_time(self, symbol: str, interval: str) -> Optional[int]:
        row = self.db.execute("SELECT max(open_time) FROM klines WHERE symbol=? AND interval=?", (symbol, interval)).fetchone()
        return None if row is None or row[0] is None else int(row[0])

    def klines(self, symbol: str, interval: str, start_ms: Optional[int] = None, end_ms: Optional[int] = None) -> List[dict]:
        sql = "SELECT open_time, open, high, low, close, volume, close_time, taker_buy_base FROM klines WHERE symbol=? AND interval=?"
        args: list = [symbol, interval]
        if start_ms is not None:
            sql += " AND open_time>=?"
            args.append(int(start_ms))
        if end_ms is not None:
            sql += " AND open_time<?"
            args.append(int(end_ms))
        sql += " ORDER BY open_time"
        return [{
            "time": r[0], "open": r[1], "high": r[2], "low": r[3], "close": r[4], "volume": r[5],
            "close_time": r[6], "taker_buy_base": r[7], "is_closed": True,
        } for r in self.db.execute(sql, args)]

    def coverage(self, symbol: str = "BTCUSDT") -> dict:
        out = {}
        for interval in INTERVAL_MS:
            row = self.db.execute(
                "SELECT count(*), min(open_time), max(open_time) FROM klines WHERE symbol=? AND interval=?",
                (symbol, interval)).fetchone()
            out[interval] = {"count": row[0], "start": row[1], "end": row[2]}
        for table, column in (("funding_rates", "funding_time"), ("open_interest", "time"), ("taker_ratio", "time")):
            row = self.db.execute(f"SELECT count(*), min({column}), max({column}) FROM {table} WHERE symbol=?", (symbol,)).fetchone()
            out[table] = {"count": row[0], "start": row[1], "end": row[2]}
        return out

    def confirmation(self, symbol: str, at_ms: int) -> dict:
        from .derivatives import confirmation_view

        oi_now = self.db.execute(
            "SELECT oi FROM open_interest WHERE symbol=? AND time<=? ORDER BY time DESC LIMIT 1", (symbol, at_ms)).fetchone()
        oi_prev = self.db.execute(
            "SELECT oi FROM open_interest WHERE symbol=? AND time<=? ORDER BY time DESC LIMIT 1",
            (symbol, at_ms - 3_600_000)).fetchone()
        funding = self.db.execute(
            "SELECT rate FROM funding_rates WHERE symbol=? AND funding_time<=? ORDER BY funding_time DESC LIMIT 1",
            (symbol, at_ms)).fetchone()
        taker = self.db.execute(
            "SELECT sell_buy_ratio FROM taker_ratio WHERE symbol=? AND time<=? AND time>=? ORDER BY time DESC LIMIT 1",
            (symbol, at_ms, at_ms - 900_000)).fetchone()
        return confirmation_view(
            None if oi_now is None else oi_now[0], None if oi_prev is None else oi_prev[0],
            None if funding is None else funding[0], None if taker is None else taker[0], at_ms)


def backfill_klines(store: ResearchStore, interval: str, start_ms: int, end_ms: int,
                    symbol: str = "BTCUSDT", sleep_s: float = 0.05) -> int:
    step = INTERVAL_MS[interval]
    have = store.max_open_time(symbol, interval)
    cursor = start_ms if have is None else max(start_ms, have + step)
    written = 0
    while cursor < end_ms:
        raw = get_json(KLINE_URL.format(symbol=symbol, interval=interval, start=cursor, end=end_ms))
        if not raw:
            break
        bars = [bar_from_kline(row) for row in raw if int(row[6]) < end_ms]
        written += store.upsert_klines(symbol, interval, bars)
        nxt = int(raw[-1][0]) + step
        print(f"klines {interval} +{len(bars)} through {raw[-1][0]}", flush=True)
        if nxt <= cursor or len(raw) < 1000:
            break
        cursor = nxt
        time.sleep(sleep_s)
    return written


def backfill_funding(store: ResearchStore, start_ms: int, end_ms: int, symbol: str = "BTCUSDT") -> int:
    cursor = start_ms
    written = 0
    while cursor < end_ms:
        raw = get_json(FUNDING_URL.format(symbol=symbol, start=cursor))
        if not raw:
            break
        rows = [{"time": int(row["fundingTime"]), "rate": float(row["fundingRate"])}
                for row in raw if int(row["fundingTime"]) <= end_ms]
        written += store.upsert_funding(symbol, rows)
        nxt = int(raw[-1]["fundingTime"]) + 1
        if nxt <= cursor or len(raw) < 1000:
            break
        cursor = nxt
        time.sleep(0.05)
    return written


def backfill(store: ResearchStore, start_ms: int, end_ms: int, intervals: Optional[List[str]] = None,
             symbol: str = "BTCUSDT") -> dict:
    intervals = intervals or ["1d", "4h", "1h", "15m", "5m", "1m"]
    result = {interval: backfill_klines(store, interval, start_ms, end_ms, symbol) for interval in intervals}
    try:
        result["funding"] = backfill_funding(store, start_ms, end_ms, symbol)
    except Exception as exc:
        result["fundingError"] = type(exc).__name__
    return result


def main(argv=None):
    import argparse
    from pathlib import Path

    parser = argparse.ArgumentParser(description="Backfill the BTCUSDT research library")
    parser.add_argument("--db", default="data/research.sqlite3")
    parser.add_argument("--years", type=float, default=2.0)
    parser.add_argument("--intervals", default="1d,4h,1h,15m,5m,1m")
    args = parser.parse_args(argv)
    path = Path(args.db)
    path.parent.mkdir(parents=True, exist_ok=True)
    end = int(time.time() * 1000)
    start = end - int(args.years * 365 * 24 * 3600 * 1000)
    store = ResearchStore(str(path))
    try:
        summary = backfill(store, start, end, [item for item in args.intervals.split(",") if item])
        print({"wrote": summary, "coverage": store.coverage()})
    finally:
        store.close()


if __name__ == "__main__":
    main()
