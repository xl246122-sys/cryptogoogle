"""Tick-level exit classification for a short-horizon-v2 position.

The live book calls this on every quote. Closed-bar settlement stays in the
tracker so a research replay does not depend on which ticks were sampled.
Same-bar ambiguity is not resolved here: a touch of the stop is a stop alert.
"""
from typing import Optional, Sequence, Tuple

from .config import V2_ENV_DROP_5M_PCT, V2_NEAR_STOP_PCT
from .indicators import ema


def classify_exit(bid: float, now_ms: int, entry: Optional[float], entry_at: int, stop: float, tp1: float,
                  tp2: float, invalidation: float, reclaim: Optional[float], breakeven: Optional[float],
                  sold: bool, max_hold_minutes: int, time_stop_minutes: int, time_stop_progress_r: float,
                  m1: Optional[Sequence[dict]], m15: Optional[Sequence[dict]], h1: Optional[Sequence[dict]],
                  fresh: bool) -> Optional[Tuple[str, str]]:
    """Return (kind, Chinese message). None means no new reminder."""
    if now_ms >= entry_at + int(max_hold_minutes) * 60_000:
        return "TIME_EXIT", "持有已满 6 小时，市价或挂单离场。"
    if not fresh or entry is None:
        return None
    if sold:
        if isinstance(breakeven, (int, float)) and bid <= breakeven:
            return "BREAKEVEN_EXIT", "价格回到保本价，余仓离场。"
        if bid >= tp2:
            return "TP2_EXIT", "到达 TP2，余仓离场。"
        bars15 = [bar for bar in (m15 or []) if bar.get("close_time", 0) <= now_ms]
        level = ema([bar["close"] for bar in bars15][-120:], 20) if len(bars15) >= 20 else None
        if level is not None and bars15[-1]["close"] < level and bars15[-1]["close_time"] > entry_at:
            return "TRAIL_EXIT", "15 分钟收盘跌破 EMA20，余仓离场。"
    elif bid <= stop:
        return "STOP_EXIT", "成交价已到止损，立即卖出。"
    minute = [bar for bar in (m1 or []) if bar.get("close_time", 0) <= now_ms][-5:]
    if (len(minute) >= 5 and minute[0]["open"] > 0
            and (minute[0]["open"] - minute[-1]["close"]) / minute[0]["open"] * 100 >= V2_ENV_DROP_5M_PCT):
        return "ENV_EXIT", "5 分钟内下跌达到 1%，多单离场或减半。"
    hourly = [bar for bar in (h1 or []) if bar.get("close_time", 0) <= now_ms]
    if hourly and hourly[-1]["close"] < invalidation:
        return "ENV_EXIT", "1 小时收盘跌破环境支撑，多单离场或减半。"
    if not sold and bid >= tp1:
        return "TP1_PARTIAL_EXIT", "到达 TP1，卖出 50%，止损上移到保本。"
    risk = entry - stop
    progress = ((bid - entry) / risk) if risk > 0 else 0.0
    if now_ms >= entry_at + int(time_stop_minutes) * 60_000 and progress < float(time_stop_progress_r):
        return "TIME_STOP_EXIT", "90 分钟未到 +0.3R，动能不足，离场。"
    if stop > 0 and (bid - stop) / stop * 100 <= V2_NEAR_STOP_PCT:
        return "STOP_NEAR_WARNING", "价格距止损不足 0.15%，考虑减仓。"
    bars15 = [bar for bar in (m15 or []) if bar.get("close_time", 0) <= now_ms]
    if isinstance(reclaim, (int, float)) and bars15 and stop < bars15[-1]["close"] < reclaim:
        return "STRUCTURE_WARNING", "15 分钟收盘跌回收复价下方，结构正在失效。"
    if bars15 and stop < bars15[-1]["close"] < invalidation:
        return "STRUCTURE_WARNING", "15 分钟收盘跌回失效位下方，结构正在失效。"
    return None
