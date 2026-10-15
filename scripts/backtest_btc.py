#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Offline research helper for Crypto-G V1.07.

This does not place orders. It also does not invent a win rate.

Production BUY candidates need a live order book and 240 closed 15m bars.
Historical order-book snapshots are not available from klines, so this script
does not count production BUY signals and does not fall back to synthetic prices.
"""

import sys
from datetime import datetime, timezone

BINANCE_API_BASES = [
    "https://data-api.binance.vision/api/v3",
    "https://api.binance.com/api/v3",
]


def fetch_klines(symbol: str, interval: str, limit: int):
    import requests
    session = requests.Session()
    session.headers.update({"User-Agent": "CryptoG-Backtest/1.07"})
    for base in BINANCE_API_BASES:
        try:
            res = session.get(
                f"{base}/klines",
                params={"symbol": symbol, "interval": interval, "limit": limit},
                timeout=8,
            )
            if res.status_code != 200:
                continue
            raw = res.json()
            if not isinstance(raw, list) or not raw:
                continue
            candles = []
            for row in raw:
                candles.append({
                    "time": int(row[0]),
                    "open": float(row[1]),
                    "high": float(row[2]),
                    "low": float(row[3]),
                    "close": float(row[4]),
                    "volume": float(row[5]),
                    "close_time": int(row[6]),
                    "taker_buy_base": float(row[9]) if len(row) > 9 else 0.0,
                })
            return candles
        except Exception:
            continue
    return []


def main():
    symbol = "BTCUSDT"
    micro = fetch_klines(symbol, "1m", 1500)
    regime = fetch_klines(symbol, "15m", 240)
    hourly = fetch_klines(symbol, "1h", 48)
    if len(micro) < 200 or len(regime) < 240 or len(hourly) < 15:
        print("UNVERIFIED: Binance klines were not fully available.")
        print("No synthetic series was substituted, and no win rate was calculated.")
        sys.exit(1)

    start = datetime.fromtimestamp(micro[0]["time"] / 1000, tz=timezone.utc)
    end = datetime.fromtimestamp(micro[-1]["close_time"] / 1000, tz=timezone.utc)
    print("Crypto-G V1.07 offline data check")
    print(f"Symbol: {symbol}")
    print(f"1m bars: {len(micro)}  from {start.isoformat()} to {end.isoformat()}")
    print(f"15m bars: {len(regime)}  1h bars: {len(hourly)}")
    print("Production BUY count: not calculated.")
    print("Reason: historical bid/ask depth is not in kline data, and the live gate requires it.")
    print("Overlapping trade sums from the previous backtest are not used.")


if __name__ == "__main__":
    main()
