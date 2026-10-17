"""Download closed BTCUSDT klines for the short-horizon-v2 replay fixture.

Rows are compact: [open_time, open, high, low, close, volume, close_time, taker_buy_base].
"""
import json
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

CST = timezone(timedelta(hours=8))
END = int(datetime(2026, 10, 17, 12, 0, tzinfo=CST).timestamp() * 1000)
REPLAY_START = int(datetime(2026, 10, 8, 0, 0, tzinfo=CST).timestamp() * 1000)
PLAN = {
    "1d": (86_400_000, END - 500 * 86_400_000),
    "4h": (14_400_000, END - 500 * 14_400_000),
    "1h": (3_600_000, REPLAY_START - 300 * 3_600_000),
    "15m": (900_000, REPLAY_START - 200 * 900_000),
    "5m": (300_000, REPLAY_START),
    "1m": (60_000, int(datetime(2026, 10, 10, 22, 0, tzinfo=CST).timestamp() * 1000)),
}
OUT = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "btc_v2_20261008_17.json"


def fetch(interval, step, start):
    rows, cursor = [], start
    while cursor < END:
        url = ("https://data-api.binance.vision/api/v3/klines?symbol=BTCUSDT"
               f"&interval={interval}&startTime={cursor}&endTime={END - 1}&limit=1000")
        for attempt in range(5):
            try:
                with urllib.request.urlopen(url, timeout=30) as response:
                    batch = json.load(response)
                break
            except OSError:
                time.sleep(1 + attempt)
        else:
            raise RuntimeError(f"fetch failed: {interval}")
        if not batch:
            break
        rows.extend(batch)
        cursor = batch[-1][0] + step
        if len(batch) < 1000:
            break
    return [[r[0], float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5]), r[6], float(r[9])]
            for r in rows if r[6] < END]


def main():
    data = {"symbol": "BTCUSDT", "source": "data-api.binance.vision", "endMs": END,
            "columns": ["time", "open", "high", "low", "close", "volume", "close_time", "taker_buy_base"]}
    for interval, (step, start) in PLAN.items():
        data[interval] = fetch(interval, step, start)
        print(interval, len(data[interval]), file=sys.stderr)
    OUT.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
    print(OUT, OUT.stat().st_size, file=sys.stderr)


if __name__ == "__main__":
    main()
