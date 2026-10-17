"""Shared 10m-trigger / 30m-structure / 1h-regime contract for both engines.

Prices come from closed candles. A failing cost check drops the setup.
"""
import math
from typing import List, Optional

FRICTION = 0.11
MIN_RR = 1.10
FRESH_MS = 180_000
BUCKET_MS = 90 * 60 * 1000

FLUSH = "FLUSH_RECLAIM"
PULLBACK = "PULLBACK_RECLAIM"


def aggregate(bars: List[dict], source_step: int, target_step: int) -> List[dict]:
    """Exact closed buckets only. A partial or gapped bucket is omitted."""
    if source_step <= 0 or target_step < source_step or target_step % source_step:
        raise ValueError("bad aggregate steps")
    need = target_step // source_step
    groups = {}
    for bar in bars:
        if bar.get("is_closed") is False:
            continue
        bucket = (int(bar["time"]) // target_step) * target_step
        groups.setdefault(bucket, []).append(bar)
    out = []
    for bucket in sorted(groups):
        chunk = sorted(groups[bucket], key=lambda item: item["time"])
        if len(chunk) != need or chunk[0]["time"] != bucket:
            continue
        if any(chunk[i + 1]["time"] - chunk[i]["time"] != source_step for i in range(need - 1)):
            continue
        out.append({
            "time": bucket,
            "close_time": chunk[-1]["close_time"],
            "open": chunk[0]["open"],
            "high": max(item["high"] for item in chunk),
            "low": min(item["low"] for item in chunk),
            "close": chunk[-1]["close"],
            "volume": sum(item.get("volume") or 0 for item in chunk),
            "taker_buy_base": sum(item.get("taker_buy_base") or 0 for item in chunk),
            "is_closed": True,
        })
    return out


def confirmed_highs(bars: List[dict]) -> List[float]:
    highs = []
    for index in range(2, len(bars) - 2):
        high = bars[index]["high"]
        neighbours = [bars[index + offset]["high"] for offset in (-2, -1, 1, 2)]
        if high >= max(neighbours) and high > min(neighbours):
            highs.append(high)
    return highs


def _target(entry: float, highs: List[float]) -> Optional[float]:
    above = sorted(high for high in highs if high > entry)
    if not above:
        return None
    target = math.floor(above[0] * 0.9995 * 100) / 100
    return target if target > entry else None


def _tier(entry: float, stop: float, target: float) -> Optional[dict]:
    if not (stop < entry < target):
        return None
    risk = (entry - stop) / entry * 100
    gross = (target / entry - 1) * 100
    net = gross - FRICTION
    if risk <= 0 or net <= 0:
        return None
    reward = net / (risk + FRICTION)
    if reward < MIN_RR - 1e-9:
        return None
    if risk <= 1.80 + 1e-9 and net >= 0.59 - 1e-9:
        hold, floor = 240, 0.59
    elif risk <= 0.90 + 1e-9 and net >= 0.40 - 1e-9:
        hold, floor = 45, 0.40
    else:
        return None
    return {"hold": hold, "min_net": floor, "risk": risk, "gross": gross, "net": net, "rr": reward}


def _waterfall(m30: List[dict]) -> bool:
    last = m30[-3:]
    closes = [bar["close"] for bar in last]
    lows = [bar["low"] for bar in last]
    return closes[0] > closes[1] > closes[2] and lows[0] > lows[1] > lows[2]


def _pack(module: str, entry: float, stop: float, invalidation: float, target: float,
          confirmation: int, swing_time: int, now_ms: int, reason: str, tier: dict) -> dict:
    strategy = "FLASH_CRASH_REBOUND" if module == FLUSH else "TREND_PULLBACK_BUY"
    model = "REBOUND" if module == FLUSH else "PULLBACK"
    name = "BTC 急跌收回" if module == FLUSH else "BTC 回踩收回"
    ttl = 90 * 60 * 1000 if module == FLUSH else 30 * 60 * 1000
    bucket = int(confirmation) // BUCKET_MS
    return {
        "module": module,
        "strategy": strategy,
        "model": model,
        "name_zh": name,
        "entry": entry,
        "stop": stop,
        "invalidation": invalidation,
        "target": target,
        "hold": tier["hold"],
        "min_net": tier["min_net"],
        "net": tier["net"],
        "gross": tier["gross"],
        "risk": tier["risk"],
        "rr": tier["rr"],
        "confirmation_ms": confirmation,
        "ttl_ms": ttl,
        "expires_at": now_ms + ttl,
        "reason": reason,
        "structure_key": f"BTCUSDT_{strategy}_{int(swing_time)}_{bucket}",
        "anchor_time_ms": int(swing_time),
        "anchor_timeframe": "30m",
    }


def _flush(m30: List[dict], m10: List[dict], entry: float, now_ms: int) -> Optional[dict]:
    if len(m30) < 16 or not m10:
        return None
    trigger = m10[-1]
    if not 0 <= now_ms - int(trigger["close_time"]) <= FRESH_MS:
        return None
    recent = m30[-8:]
    low_bar = min(recent, key=lambda bar: bar["low"])
    prior = [bar for bar in m30 if bar["time"] < low_bar["time"] and low_bar["time"] - bar["time"] <= 12 * 3600 * 1000]
    if len(prior) < 4:
        return None
    swing_high = max(bar["high"] for bar in prior)
    swing_low = low_bar["low"]
    if swing_high <= 0 or not 2.5 <= (swing_high - swing_low) / swing_high * 100 <= 6.0:
        return None
    if m30[-1]["time"] != low_bar["time"] and m30[-1]["low"] < m30[-2]["low"]:
        return None
    if trigger["low"] > swing_low * 1.0035:
        return None
    span = trigger["high"] - trigger["low"]
    if span <= 0 or trigger["close"] < trigger["low"] + span * 0.5:
        return None
    if trigger["close"] < swing_low * 1.004:
        return None
    if (entry - swing_low) / swing_low * 100 > 2.0:
        return None
    stop = math.floor(swing_low * 0.9995 * 100) / 100
    target = _target(entry, confirmed_highs(m30))
    if target is None:
        return None
    tier = _tier(entry, stop, target)
    if not tier or not stop < swing_low < entry:
        return None
    return _pack(FLUSH, entry, stop, swing_low, target, int(trigger["close_time"]), int(low_bar["time"]), now_ms,
                 "急跌低点所在的10分钟收回跌幅中段，止损在该低点下方", tier)


def _pullback(m30: List[dict], m10: List[dict], h1: List[dict], entry: float, now_ms: int) -> Optional[dict]:
    if len(m30) < 10 or len(m10) < 2 or len(h1) < 12 or _waterfall(m30):
        return None
    trigger = m10[-1]
    if not 0 <= now_ms - int(trigger["close_time"]) <= FRESH_MS:
        return None
    ma7 = sum(bar["close"] for bar in m30[-7:]) / 7
    if not (m10[-2]["close"] < ma7 <= trigger["close"]):
        return None
    older = h1[-36:-6] if len(h1) >= 36 else h1[:-6]
    if not older:
        return None
    flush_low = min(bar["low"] for bar in older)
    recent_low = min(bar["low"] for bar in h1[-6:])
    if recent_low <= flush_low * 1.0015:
        return None
    swing = min(m30[-3:], key=lambda bar: bar["low"])
    stop = math.floor(swing["low"] * 0.9995 * 100) / 100
    target = _target(entry, confirmed_highs(m30))
    if target is None:
        return None
    tier = _tier(entry, stop, target)
    if not tier or not stop < swing["low"] < entry:
        return None
    return _pack(PULLBACK, entry, stop, swing["low"], target, int(trigger["close_time"]), int(swing["time"]), now_ms,
                 "1小时低点高于前次急跌，10分钟收盘站回30分钟MA7", tier)


def classify(m10: List[dict], m30: List[dict], h1: List[dict], entry: float, now_ms: int) -> Optional[dict]:
    if not all(math.isfinite(value) and value > 0 for value in (entry, now_ms)):
        return None
    flush = _flush(m30, m10, entry, now_ms)
    if flush:
        return flush
    return _pullback(m30, m10, h1, entry, now_ms)


def setup_from_snapshot(snapshot: dict, now_ms: int) -> Optional[dict]:
    series = snapshot.get("series") or {}
    ticker = snapshot.get("ticker") or {}
    entry = ticker.get("ask_price") or ticker.get("price")
    if not entry:
        return None
    minute = [bar for bar in series.get("1m", []) if bar.get("is_closed") and bar.get("close_time", now_ms) < now_ms]
    quarter = [bar for bar in series.get("15m", []) if bar.get("is_closed") and bar.get("close_time", now_ms) < now_ms]
    hourly = [bar for bar in series.get("1h", []) if bar.get("is_closed") and bar.get("close_time", now_ms) < now_ms]
    return classify(aggregate(minute, 60_000, 600_000), aggregate(quarter, 900_000, 1_800_000), hourly, float(entry), now_ms)
