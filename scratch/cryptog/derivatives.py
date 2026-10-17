"""Derivatives confirmation for S1, and the accumulator that starts the history.

Public open-interest history is short, so this process stores each poll.
Scoring never opens or blocks a BUY by itself: OI, funding and taker-sell
only add points on a setup the price rules already accepted.
"""
import json
import math
import threading
import time
import urllib.request
from typing import Optional

from .config import V2_DERIVATIVE_POINTS, V2_FUNDING_EXTREME, V2_OI_DROP_1H_PCT, V2_TAKER_SELL_MIN

FUNDING_URL = "https://fapi.binance.com/fapi/v1/fundingRate?symbol=BTCUSDT&limit=20"
OI_URL = "https://fapi.binance.com/futures/data/openInterestHist?symbol=BTCUSDT&period=5m&limit=500"
TAKER_URL = "https://fapi.binance.com/futures/data/takerlongshortRatio?symbol=BTCUSDT&period=5m&limit=500"
H1 = 3_600_000


def _finite(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def score_confirmation(raw: Optional[dict]) -> dict:
    """raw fields: oi_change_1h_pct (percent points), funding_rate (exchange decimal), taker_sell_ratio."""
    if not raw or raw.get("status") == "unavailable":
        return {"points": 0, "tags": [], "status": "unavailable"}
    points = 0
    tags = []
    oi = _finite(raw.get("oi_change_1h_pct"))
    funding = _finite(raw.get("funding_rate"))
    ratio = _finite(raw.get("taker_sell_ratio"))
    if oi is not None and oi <= -V2_OI_DROP_1H_PCT:
        points += V2_DERIVATIVE_POINTS
        tags.append("OI_DROP")
    if funding is not None and funding <= V2_FUNDING_EXTREME:
        points += V2_DERIVATIVE_POINTS
        tags.append("FUNDING_EXTREME")
    if ratio is not None and ratio >= V2_TAKER_SELL_MIN:
        points += V2_DERIVATIVE_POINTS
        tags.append("TAKER_SELL")
    return {
        "points": points, "tags": tags, "status": "ok",
        "oi_change_1h_pct": oi, "funding_rate": funding, "taker_sell_ratio": ratio,
    }


def tag_text(tags) -> str:
    names = {"OI_DROP": "OI 1 小时下降 ≥ 3%", "FUNDING_EXTREME": "资金费率 ≤ -0.01%", "TAKER_SELL": "主动卖出比 ≥ 1.5"}
    return "、".join(names[tag] for tag in tags if tag in names)


def _get(url: str):
    request = urllib.request.Request(url, headers={"User-Agent": "cryptog-v2"})
    with urllib.request.urlopen(request, timeout=8) as response:
        return json.loads(response.read().decode())


class DerivativesFeed(threading.Thread):
    """Polls funding, open interest and the taker ratio, and appends them to the research store."""

    def __init__(self, stop, path: str):
        super().__init__(name="v2-derivatives", daemon=True)
        self.stop = stop
        self.path = path
        self.lock = threading.Lock()
        self.snapshot = {"status": "unavailable"}
        self.error = None
        self.updated_ms = 0
        self.heartbeat_ms = 0

    def latest(self) -> dict:
        with self.lock:
            return dict(self.snapshot)

    def health(self, now_ms: int) -> dict:
        with self.lock:
            fresh = self.snapshot.get("status") == "ok" and 0 <= now_ms - self.updated_ms <= 15 * 60 * 1000
            return {"healthy": fresh, "error": self.error, "updatedMs": self.updated_ms, "snapshot": dict(self.snapshot)}

    def poll(self, now_ms: Optional[int] = None) -> dict:
        from .kline_store import ResearchStore

        now_ms = int(time.time() * 1000) if now_ms is None else now_ms
        store = ResearchStore(self.path)
        try:
            funding = _get(FUNDING_URL)
            store.upsert_funding("BTCUSDT", [
                {"time": int(row["fundingTime"]), "rate": float(row["fundingRate"])} for row in funding
            ])
            oi_rows = _get(OI_URL)
            store.upsert_open_interest("BTCUSDT", [
                {"time": int(row["timestamp"]), "oi": float(row["sumOpenInterest"])} for row in oi_rows
            ])
            taker_rows = _get(TAKER_URL)
            parsed = []
            for row in taker_rows:
                buy, sell = float(row.get("buyVol") or 0), float(row.get("sellVol") or 0)
                ratio = (sell / buy) if buy > 0 else None
                if ratio is None and float(row.get("buySellRatio") or 0) > 0:
                    ratio = 1.0 / float(row["buySellRatio"])
                if ratio is not None:
                    parsed.append({"time": int(row["timestamp"]), "sell_buy_ratio": ratio})
            store.upsert_taker("BTCUSDT", parsed)
            snapshot = store.confirmation("BTCUSDT", now_ms)
        finally:
            store.close()
        with self.lock:
            self.snapshot = snapshot
            self.updated_ms = now_ms
            self.error = None
        return snapshot

    def run(self):
        while not self.stop.is_set():
            now_ms = int(time.time() * 1000)
            self.heartbeat_ms = now_ms
            try:
                self.poll(now_ms)
            except Exception as exc:
                with self.lock:
                    self.error = type(exc).__name__
            self.stop.wait(60)


def confirmation_view(oi_now: Optional[float], oi_hour_ago: Optional[float],
                      funding_rate: Optional[float], taker_sell_ratio: Optional[float], at_ms: int) -> dict:
    if oi_now is None and funding_rate is None and taker_sell_ratio is None:
        return {"status": "unavailable", "atMs": at_ms}
    change = None
    if oi_now is not None and oi_hour_ago not in (None, 0):
        change = (oi_now / oi_hour_ago - 1) * 100.0
    return {
        "status": "ok", "atMs": at_ms, "oi_change_1h_pct": None if change is None else round(change, 4),
        "funding_rate": funding_rate, "taker_sell_ratio": None if taker_sell_ratio is None else round(taker_sell_ratio, 4),
        "oi_now": oi_now, "oi_hour_ago": oi_hour_ago, "lookbackMs": H1,
    }
