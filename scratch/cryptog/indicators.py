"""Indicators on the same definitions as the Binance chart.

EMA seeds with the SMA of the first n closes, RSI and ATR use Wilder smoothing,
BOLL uses the population standard deviation. Inputs are oldest-first lists.
"""
import math
from typing import List, Optional, Sequence


def ema_series(values: Sequence[float], n: int) -> List[Optional[float]]:
    out: List[Optional[float]] = [None] * len(values)
    if n <= 0 or len(values) < n:
        return out
    k = 2 / (n + 1)
    cur = sum(values[:n]) / n
    out[n - 1] = cur
    for i in range(n, len(values)):
        cur = values[i] * k + cur * (1 - k)
        out[i] = cur
    return out


def ema(values: Sequence[float], n: int) -> Optional[float]:
    series = ema_series(values, n)
    return series[-1] if series else None


def sma(values: Sequence[float], n: int) -> Optional[float]:
    if n <= 0 or len(values) < n:
        return None
    return sum(values[-n:]) / n


def boll(values: Sequence[float], n: int = 20, k: float = 2.0) -> Optional[dict]:
    if len(values) < n:
        return None
    window = values[-n:]
    mid = sum(window) / n
    sd = math.sqrt(sum((x - mid) ** 2 for x in window) / n)
    return {"up": mid + k * sd, "mid": mid, "dn": mid - k * sd, "width": (2 * k * sd) / mid if mid else 0.0}


def rsi_series(values: Sequence[float], n: int) -> List[Optional[float]]:
    out: List[Optional[float]] = [None] * len(values)
    if n <= 0 or len(values) <= n:
        return out
    gains = [max(values[i] - values[i - 1], 0.0) for i in range(1, len(values))]
    losses = [max(values[i - 1] - values[i], 0.0) for i in range(1, len(values))]
    avg_gain = sum(gains[:n]) / n
    avg_loss = sum(losses[:n]) / n

    def value(g, l):
        if l == 0:
            return 100.0 if g > 0 else 50.0
        return 100 - 100 / (1 + g / l)

    out[n] = value(avg_gain, avg_loss)
    for i in range(n, len(gains)):
        avg_gain = (avg_gain * (n - 1) + gains[i]) / n
        avg_loss = (avg_loss * (n - 1) + losses[i]) / n
        out[i + 1] = value(avg_gain, avg_loss)
    return out


def rsi(values: Sequence[float], n: int) -> Optional[float]:
    series = rsi_series(values, n)
    return series[-1] if series else None


def atr(bars: Sequence[dict], n: int = 14) -> Optional[float]:
    if len(bars) <= n:
        return None
    trs = [max(b["high"] - b["low"], abs(b["high"] - a["close"]), abs(b["low"] - a["close"]))
           for a, b in zip(bars, bars[1:])]
    cur = sum(trs[:n]) / n
    for tr in trs[n:]:
        cur = (cur * (n - 1) + tr) / n
    return cur


def frame(bars: Sequence[dict]) -> Optional[dict]:
    """Chart readings for the latest closed bar of one timeframe."""
    if len(bars) < 100:
        return None
    closes = [b["close"] for b in bars]
    band = boll(closes)
    values = {
        "close": closes[-1],
        "close_time": int(bars[-1]["close_time"]),
        "ema7": ema(closes, 7),
        "ema25": ema(closes, 25),
        "ema99": ema(closes, 99),
        "rsi6": rsi(closes, 6),
        "rsi14": rsi(closes, 14),
        "atr14": atr(bars, 14),
        "boll_up": band["up"],
        "boll_mid": band["mid"],
        "boll_dn": band["dn"],
    }
    if any(v is None or not math.isfinite(v) for v in values.values()):
        return None
    return values
