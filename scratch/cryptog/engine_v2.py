"""Engine A, short-horizon-v2: 1D/4H/1H context, S1-S5 setups and the trade plan.

Pure functions. Bars are closed candles, oldest first; the caller supplies the time.
Every price, stop, target and size comes from here. The AI reviewer never edits them.
"""
import math
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple

from .config import (
    V2_CONTEXT_MAX_AGE_MS, V2_ENTRY_ABOVE_PCT, V2_ENTRY_BELOW_PCT, V2_ESCAPE_PCT, V2_FRICTION_PCT,
    V2_MAX_HOLD_MINUTES, V2_MIN_NET_RR, V2_MIN_NET_TP1, V2_RISK_PER_TRADE_PCT, V2_RULE_VERSION,
    V2_S1_BEAR_EXTRA_PCT,
    V2_S1_MIN_DROP_PCT, V2_S1_MIN_VOLUME_MULT, V2_S1_STOP_ATR, V2_S2_ENTRY_MAX_PCT, V2_S2_ENTRY_MIN_PCT,
    V2_S2_STOP_PCT, V2_S2_TOUCH_PCT, V2_S2_WICK_TO_BODY, V2_S3_ENTRY_BAND_PCT, V2_S3_RSI_MAX,
    V2_S3_STOP_ATR, V2_S4_BAND_LOOKBACK, V2_S4_BAND_PERCENTILE, V2_S4_BREAK_BARS, V2_S4_SESSION_END_UTC,
    V2_S4_SESSION_START_UTC, V2_S4_STOP_ATR, V2_S4_VOLUME_MULT, V2_S5_PRIOR_SESSIONS, V2_S5_VOLUME_MULT,
    V2_STOP_MAX_PCT, V2_STOP_MIN_PCT, V2_TIER_LABEL, V2_TIER_WATCH, V2_TIME_STOP_MINUTES,
    V2_TIME_STOP_PROGRESS_R, V2_TP1_FRACTION,
)
from .cost_model import position_fraction_pct
from .derivatives import score_confirmation, tag_text
from .indicators import atr, boll, ema, frame, rsi_series

M5, M15, H1 = 300_000, 900_000, 3_600_000
CST = timezone(timedelta(hours=8))
TARGET_BUFFER = 0.9995
STATE_ZH = {"UP": "多头", "ABOVE_99": "多头回调", "BELOW_99": "空头反弹", "DOWN": "空头"}
STATE_SCORE = {"UP": 1.0, "ABOVE_99": 0.5, "BELOW_99": -0.5, "DOWN": -1.0}
WEIGHTS = {"d1": 0.45, "h4": 0.35, "h1": 0.20}
MODULES = {
    "S1": {"strategy": "FLASH_CRASH_REBOUND", "model": "REBOUND", "name": "急跌收复", "valid_ms": 2 * M15},
    "S2": {"strategy": "RANGE_OSCILLATION", "model": "RANGE", "name": "支撑回踩", "valid_ms": 2 * M15},
    "S3": {"strategy": "TREND_PULLBACK_BUY", "model": "PULLBACK", "name": "趋势回踩", "valid_ms": 2 * M5},
    "S4": {"strategy": "BURST_BREAKOUT", "model": "BREAKOUT", "name": "收敛突破", "valid_ms": 2 * M15},
}


def _fmt(price: float) -> str:
    return f"{price:,.0f}"


def confirmed_highs(bars: List[dict]) -> List[dict]:
    """Two closed bars on each side; the newest two bars cannot be pivots yet."""
    out = []
    for i in range(2, len(bars) - 2):
        high = bars[i]["high"]
        around = [bars[j]["high"] for j in (i - 2, i - 1, i + 1, i + 2)]
        if high >= max(around) and high > min(around):
            out.append({"time": int(bars[i]["time"]), "high": high})
    return out


def flush_lows(h1: List[dict]) -> List[float]:
    """1H pivot lows that ended a >=2% drop and were followed by a >=1.5% rebound."""
    out = []
    window = h1[-120:]
    for i in range(12, len(window) - 2):
        low = window[i]["low"]
        if low > min(window[j]["low"] for j in (i - 2, i - 1, i + 1, i + 2)):
            continue
        prior_high = max(b["high"] for b in window[i - 12:i])
        after_high = max(b["high"] for b in window[i + 1:i + 13])
        if prior_high >= low * 1.02 and after_high >= low * 1.015:
            out.append(low)
    return sorted(set(out))[-3:]


def squeeze_threshold(m15: List[dict]) -> Optional[float]:
    """20th percentile of 15m BOLL width over the 200 bars before the newest."""
    lookback = V2_S4_BAND_LOOKBACK
    if len(m15) < lookback + 20:
        return None
    closes = [b["close"] for b in m15]
    widths = [boll(closes[:j + 1])["width"] for j in range(len(closes) - lookback - 1, len(closes) - 1)]
    widths.sort()
    return widths[min(len(widths) - 1, int(V2_S4_BAND_PERCENTILE * len(widths)))]


def build_context(d1: List[dict], h4: List[dict], h1: List[dict], m15: List[dict], at_ms: int,
                  with_squeeze: bool = True) -> Optional[dict]:
    """Closed higher-timeframe readings. Built from REST history, refreshed every 15 minutes."""
    frames = {"d1": frame(d1), "h4": frame(h4), "h1": frame(h1)}
    if any(v is None for v in frames.values()):
        return None
    highs = confirmed_highs(h1[-96:])
    return {
        "version": "context-v2",
        "atMs": int(at_ms),
        **frames,
        "h1SwingHighs": [h["high"] for h in highs[-16:]],
        "rangeHigh48h": max(b["high"] for b in h1[-48:]),
        "flushLows": flush_lows(h1),
        "m15SqueezeWidth": squeeze_threshold(m15) if with_squeeze else None,
    }


def trend_state(price: float, f: dict) -> str:
    e25, e99 = f["ema25"], f["ema99"]
    if price > e25 > e99:
        return "UP"
    if price < e25 < e99:
        return "DOWN"
    return "ABOVE_99" if price >= e99 else "BELOW_99"


def environment(ctx: dict, price: float, at_ms: int) -> dict:
    states = {tf: trend_state(price, ctx[tf]) for tf in WEIGHTS}
    score = round(100 * sum(WEIGHTS[tf] * STATE_SCORE[s] for tf, s in states.items()))
    h4_above = price > ctx["h4"]["ema99"]
    hour = datetime.fromtimestamp(at_ms / 1000, timezone.utc).hour
    daily_bull = ctx["d1"]["close"] > ctx["d1"]["ema99"]
    # 4H 未破位: the 4H close is still above the daily EMA99, the last line of the daily bull.
    # A 4H close under its own EMA99 closes S3/S4 only; S1 and S2 stay open.
    h4_intact = ctx["h4"]["close"] > ctx["d1"]["ema99"]
    gates = {
        "S1": True,
        "S2": daily_bull and h4_intact,
        "S3": h4_above and states["h4"] == "UP" and states["h1"] == "UP",
        "S4": h4_above and states["h4"] != "DOWN" and V2_S4_SESSION_START_UTC <= hour < V2_S4_SESSION_END_UTC,
    }
    closed = []
    if not h4_above:
        closed.append(f"S3/S4 关闭：4H 收盘未站上 EMA99 {_fmt(ctx['h4']['ema99'])}")
    if not gates["S2"]:
        if not daily_bull:
            closed.append(f"S2 关闭：日线已跌破 EMA99 {_fmt(ctx['d1']['ema99'])}")
        elif not h4_intact:
            closed.append(f"S2 关闭：4H 收盘跌破日线 EMA99 {_fmt(ctx['d1']['ema99'])}")
    label = " · ".join(f"{name} {STATE_ZH[states[tf]]}" for tf, name in (("d1", "1D"), ("h4", "4H"), ("h1", "1H")))
    return {"states": states, "score": score, "gates": gates, "h4AboveEma99": h4_above,
            "label": f"{label}（评分 {score:+d}）", "closed": closed}


def _avg_volume(bars: List[dict]) -> float:
    return sum(b["volume"] for b in bars) / len(bars) if bars else 0.0


def _resistances(ctx: dict) -> List[float]:
    levels = list(ctx.get("h1SwingHighs", []))
    for tf, key in (("h4", "boll_mid"), ("h4", "ema25"), ("h4", "ema99"), ("h4", "boll_up"),
                    ("d1", "ema7"), ("d1", "ema25"), ("d1", "boll_mid")):
        levels.append(ctx[tf][key])
    return sorted(levels)


def _next_above(levels: List[float], floor: float) -> Optional[float]:
    above = [math.floor(p * TARGET_BUFFER * 100) / 100 for p in levels if p * TARGET_BUFFER > floor]
    return min(above) if above else None


def detect_s1(m15: List[dict], ctx: dict, env: dict) -> Optional[dict]:
    """Flush reclaim on a closed 15m bar.

    Drop from the 12h high is at least 2.5%, and 3.5% when the 4H state is bearish.
    The low bar's volume is at least 2.5x its prior 20-bar average, and a green 15m
    close is back above that bar's midpoint. The limit band sits on the reclaim close.
    """
    if len(m15) < 75:
        return None
    trigger = m15[-1]
    low_bar = min(m15[-4:], key=lambda b: b["low"])
    li = m15.index(low_bar, len(m15) - 4)
    prior = m15[li - 48:li]
    peak = max(b["high"] for b in prior)
    low = low_bar["low"]
    drop = (peak - low) / peak * 100
    bearish = env["states"]["h4"] == "DOWN"
    need = V2_S1_MIN_DROP_PCT + (V2_S1_BEAR_EXTRA_PCT if bearish else 0.0)
    if drop < need:
        if bearish and drop >= V2_S1_MIN_DROP_PCT:
            return {"module": "S1", "blocked": f"距 12 小时高点急跌 {drop:.2f}%，4H 空头要求 ≥{need:.1f}%，不触发",
                    "anchor_time": int(low_bar["time"]),
                    "features": {"dropPct": round(drop, 2), "dropRequiredPct": need}}
        return None
    vol_mult = low_bar["volume"] / max(_avg_volume(m15[li - 20:li]), 1e-12)
    if vol_mult < V2_S1_MIN_VOLUME_MULT:
        return None
    mid = (low_bar["high"] + low_bar["low"]) / 2
    if not (trigger["close"] > trigger["open"] and trigger["close"] > mid):
        return None
    atr15 = atr(m15[-60:], 14)
    ref = trigger["close"]
    entry_min = ref * (1 - V2_ENTRY_BELOW_PCT / 100)
    entry_max = ref * (1 + V2_ENTRY_ABOVE_PCT / 100)
    swing = _next_above(ctx.get("h1SwingHighs", []), entry_max)
    by_atr = math.floor((ref + ctx["h1"]["atr14"]) * 100) / 100
    tp1 = min(x for x in (swing, by_atr) if x is not None)
    return {
        "module": "S1", "trigger": trigger, "entry_ref": ref, "entry_min": entry_min, "entry_max": entry_max,
        "stop": math.floor((low - V2_S1_STOP_ATR * atr15) * 100) / 100, "invalidation": low, "tp1": tp1,
        "anchor_time": int(low_bar["time"]),
        "tp1_basis": "最近 1H 已确认高点内侧" if swing is not None and tp1 == swing else "1 倍 1H ATR",
        "features": {"dropPct": round(drop, 2), "dropRequiredPct": need, "volumeMultiple": round(vol_mult, 2),
                     "reclaimAboveMidPct": round((trigger["close"] / mid - 1) * 100, 3),
                     "h4Bearish": bearish},
        "reason": (f"距 12 小时高点 {_fmt(peak)} 急跌 {drop:.2f}%（要求 ≥{need:.1f}%），低点 K 线放量 {vol_mult:.1f} 倍，"
                   f"15m 阳线收回该 K 线中轴 {_fmt(mid)}，挂单在收回价 {_fmt(ref)}"
                   + ("；4H 空头，跌幅要求已加 1%" if bearish else "")),
    }


def detect_s2(m15: List[dict], ctx: dict, env: dict) -> Optional[dict]:
    """Support retest: a 15m wick into a key level (±0.3%) that closes back above it."""
    if len(m15) < 60:
        return None
    trigger = m15[-1]
    body = abs(trigger["close"] - trigger["open"])
    wick = min(trigger["open"], trigger["close"]) - trigger["low"]
    atr15 = atr(m15[-60:], 14)
    if wick < V2_S2_WICK_TO_BODY * body:
        return None
    supports = [("4H 布林下轨", ctx["h4"]["boll_dn"]), ("1D 布林下轨", ctx["d1"]["boll_dn"]),
                ("1D EMA7", ctx["d1"]["ema7"]), ("1D EMA25", ctx["d1"]["ema25"]), ("1D EMA99", ctx["d1"]["ema99"])]
    supports += [("前急跌低点", low) for low in ctx.get("flushLows", [])]
    band = V2_S2_TOUCH_PCT / 100
    touched = [(name, level) for name, level in supports
               if level * (1 - band) <= trigger["low"] <= level * (1 + band) and trigger["close"] >= level]
    if not touched:
        return None
    name, level = max(touched, key=lambda item: item[1])
    entry_min = level * (1 + V2_S2_ENTRY_MIN_PCT / 100)
    entry_max = level * (1 + V2_S2_ENTRY_MAX_PCT / 100)
    range_high = ctx["rangeHigh48h"]
    targets = [ctx["h4"]["boll_mid"], (range_high + level) / 2]
    tp1 = _next_above(targets, entry_max)
    if tp1 is None:
        return None
    return {
        "module": "S2", "trigger": trigger, "entry_ref": level, "entry_min": entry_min, "entry_max": entry_max,
        "stop": math.floor(level * (1 - V2_S2_STOP_PCT / 100) * 100) / 100,
        "invalidation": level, "tp1": tp1, "anchor_time": int(trigger["time"]) // (2 * H1) * (2 * H1),
        "anchor_name": name, "tp1_basis": "4H 中轨或 48 小时区间中线（取较近者）内侧",
        "tp2_hint": math.floor(range_high * TARGET_BUFFER * 100) / 100,
        "features": {"support": name, "wickToBody": round(wick / max(body, 1e-9), 2),
                     "wickAtr": round(wick / atr15, 2)},
        "reason": f"15m 下影线刺入{name} {_fmt(level)}（±0.3%）后收回位上，影线是实体的 {wick / max(body, 1e-9):.1f} 倍",
    }


def detect_s3(m5: List[dict], m15: List[dict], ctx: dict, env: dict) -> Optional[dict]:
    """Trend pullback: 15m RSI14 dipped below 45, then a 5m close back above the 15m EMA20."""
    if len(m5) < 2 or len(m15) < 40:
        return None
    closes = [b["close"] for b in m15]
    ema20 = ema(closes, 20)
    rsis = [v for v in rsi_series(closes, 14)[-4:] if v is not None]
    prev, trigger = m5[-2], m5[-1]
    if not rsis or min(rsis) >= V2_S3_RSI_MAX or not (prev["close"] < ema20 <= trigger["close"]):
        return None
    atr15 = atr(m15[-60:], 14)
    swing_low = min(b["low"] for b in m15[-6:])
    band = V2_S3_ENTRY_BAND_PCT / 100
    entry_min, entry_max = ema20 * (1 - band), ema20 * (1 + band)
    tp1 = _next_above(ctx.get("h1SwingHighs", []), entry_max)
    if tp1 is None:
        return None
    return {
        "module": "S3", "trigger": trigger, "entry_ref": ema20, "entry_min": entry_min, "entry_max": entry_max,
        "stop": math.floor((swing_low - V2_S3_STOP_ATR * atr15) * 100) / 100, "invalidation": swing_low, "tp1": tp1,
        "anchor_time": int(min(m15[-6:], key=lambda b: b["low"])["time"]), "tp1_basis": "1H 前高内侧",
        "features": {"rsi15Min": round(min(rsis), 1), "ema20": round(ema20, 2)},
        "reason": f"4H/1H 多头中 15m RSI14 回落到 {min(rsis):.0f}，5m 收盘重新站上 15m EMA20 {_fmt(ema20)}",
    }


def detect_s4(m15: List[dict], ctx: dict, env: dict) -> Optional[dict]:
    """Squeeze breakout: narrow 15m BOLL, then a 2x-volume close above the 16-bar high. Entry on retest."""
    threshold = ctx.get("m15SqueezeWidth")
    if threshold is None or len(m15) < 40:
        return None
    closes = [b["close"] for b in m15]
    widths = [boll(closes[:j + 1])["width"] for j in range(len(closes) - 9, len(closes) - 1)]
    trigger = m15[-1]
    box = m15[-(V2_S4_BREAK_BARS + 1):-1]
    level = max(b["high"] for b in box)
    if min(widths) > threshold or trigger["close"] <= level or trigger["volume"] < V2_S4_VOLUME_MULT * _avg_volume(m15[-21:-1]):
        return None
    height = level - min(b["low"] for b in box)
    mid = boll(closes)["mid"]
    atr15 = atr(m15[-60:], 14)
    return {
        "module": "S4", "trigger": trigger, "entry_ref": level, "entry_min": level, "entry_max": level * 1.0015,
        "stop": math.floor((min(trigger["low"], mid) - V2_S4_STOP_ATR * atr15) * 100) / 100,
        "invalidation": level * 0.998, "tp1": math.floor((level + height) * 100) / 100,
        "tp2_hint": math.floor((level + 2 * height) * 100) / 100, "breakout_level": level,
        "anchor_time": int(trigger["time"]), "tp1_basis": "1 倍收敛区高度",
        "features": {"boxHeightPct": round(height / level * 100, 2)},
        "reason": f"15m 布林带收敛后放量突破 16 根高点 {_fmt(level)}，回踩突破位挂单",
    }


def nth_sunday(year: int, month: int, n: int):
    first = datetime(year, month, 1, tzinfo=timezone.utc)
    offset = (6 - first.weekday()) % 7
    return datetime(year, month, 1 + offset + (n - 1) * 7, tzinfo=timezone.utc).date()


def us_cash_open_utc(day) -> Optional[Tuple[int, int]]:
    """US cash open in UTC. EDT 13:30 from the second Sunday in March until the first Sunday in November."""
    if day.weekday() >= 5:
        return None
    if nth_sunday(day.year, 3, 2) <= day < nth_sunday(day.year, 11, 1):
        return 13, 30
    return 14, 30


def _session_window(bar_time: int) -> Optional[Tuple[int, int]]:
    moment = datetime.fromtimestamp(bar_time / 1000, timezone.utc)
    opened = us_cash_open_utc(moment.date())
    if opened is None:
        return None
    start = int(datetime(moment.year, moment.month, moment.day, opened[0], opened[1], tzinfo=timezone.utc).timestamp() * 1000)
    return start, start + M15


def session_volumes(m15: List[dict]) -> List[dict]:
    """Completed US-open 30-minute windows: the 15m bar at the open plus the next one."""
    by_time = {int(bar["time"]): bar for bar in m15}
    found = []
    seen = set()
    for bar in m15:
        window = _session_window(int(bar["time"]))
        if window is None or window[0] in seen or int(bar["time"]) != window[0]:
            continue
        nxt = by_time.get(window[0] + M15)
        if nxt is None:
            continue
        seen.add(window[0])
        found.append({"start": window[0], "volume": bar["volume"] + nxt["volume"],
                      "open": bar["open"], "close": nxt["close"]})
    return found


def s5_baseline(m15: List[dict]) -> Optional[float]:
    """Mean of the 20 US-open windows before the latest one in this history."""
    volumes = session_volumes(m15)
    if len(volumes) < V2_S5_PRIOR_SESSIONS + 1:
        return None
    tail = volumes[-(V2_S5_PRIOR_SESSIONS + 1):-1]
    return sum(item["volume"] for item in tail) / V2_S5_PRIOR_SESSIONS


def detect_s5(m15: List[dict], baseline: Optional[float] = None) -> Optional[dict]:
    """US-open momentum. Research only: scan() never turns this into a BUY."""
    if len(m15) < 2:
        return None
    trigger, first = m15[-1], m15[-2]
    window = _session_window(int(first["time"]))
    if window is None or int(first["time"]) != window[0] or int(trigger["time"]) != window[0] + M15:
        return None
    if trigger["close"] <= first["open"]:
        return None
    volume = first["volume"] + trigger["volume"]
    if baseline is None:
        priors = [item for item in session_volumes(m15) if item["start"] < window[0]]
        if len(priors) < V2_S5_PRIOR_SESSIONS:
            return None
        baseline = sum(item["volume"] for item in priors[-V2_S5_PRIOR_SESSIONS:]) / V2_S5_PRIOR_SESSIONS
    if baseline is None or baseline <= 0 or volume < V2_S5_VOLUME_MULT * baseline:
        return None
    multiple = volume / baseline
    opened = datetime.fromtimestamp(window[0] / 1000, timezone.utc)
    return {
        "module": "S5", "tier": "RESEARCH", "push": False, "trigger": trigger,
        "anchor_time": window[0],
        "features": {"volumeMultiple": round(multiple, 3), "windowOpen": first["open"], "windowClose": trigger["close"],
                     "risePct": round((trigger["close"] / first["open"] - 1) * 100, 3)},
        "reason": (f"美盘开盘 {opened.strftime('%H:%M')} UTC 后 30 分钟收涨，量能 {multiple:.2f} 倍"
                   f"（要求 ≥ {V2_S5_VOLUME_MULT:.1f}）。只做研究，不推送"),
    }


def _metrics(price: float, stop: float, tp1: float) -> dict:
    risk = (1 - stop / price) * 100
    gross = (tp1 / price - 1) * 100
    net = gross - V2_FRICTION_PCT
    return {"risk": risk, "gross": gross, "net": net, "rr": net / (risk + V2_FRICTION_PCT) if risk > 0 else -1}


def widen_stop(setup: dict) -> dict:
    """A structural stop closer than the minimum is moved further away, never closer."""
    floor = math.floor(setup["entry_min"] * (1 - V2_STOP_MIN_PCT / 100) * 100) / 100
    if setup["stop"] > floor:
        setup = dict(setup, stop=floor, structural_stop=setup["stop"])
    return setup


def plan_issue(setup: dict) -> Optional[str]:
    """Checked at the worst band price, so every ask inside the band passes."""
    stop, tp1 = setup["stop"], setup["tp1"]
    low, high = setup["entry_min"], setup["entry_max"]
    if not stop < setup["invalidation"] < low < high < tp1:
        return "价格顺序无效：止损 < 失效位 < 挂单区间 < TP1 不成立"
    near, far = _metrics(low, stop, tp1), _metrics(high, stop, tp1)
    if near["risk"] < V2_STOP_MIN_PCT - 1e-9:
        return f"止损距离 {near['risk']:.2f}% 小于 {V2_STOP_MIN_PCT:.2f}%"
    if far["risk"] > V2_STOP_MAX_PCT + 1e-9:
        return f"止损距离 {far['risk']:.2f}% 大于 {V2_STOP_MAX_PCT:.2f}%"
    if far["net"] < V2_MIN_NET_TP1 - 1e-9:
        return f"扣 {V2_FRICTION_PCT:.2f}% 成本后 TP1 净 {far['net']:.2f}% 不足 {V2_MIN_NET_TP1:.2f}%"
    if far["rr"] < V2_MIN_NET_RR - 1e-9:
        return f"净盈亏比 {far['rr']:.2f} 不足 {V2_MIN_NET_RR:.2f}"
    return None


def _tp2(setup: dict, ctx: dict) -> float:
    hint = setup.get("tp2_hint")
    if hint and hint > setup["tp1"] * 1.001:
        return hint
    nxt = _next_above(_resistances(ctx), setup["tp1"] * 1.001)
    return nxt if nxt else math.floor((setup["tp1"] + ctx["h1"]["atr14"]) * 100) / 100


def path_issue(setup: dict, path: List[dict], now_ms: int) -> Optional[str]:
    """Bars after the trigger close: a stop touch, or a run beyond the trigger close / band top, voids the setup.

    Retest limits sit below the trigger close by design, so the escape is measured from the higher of the two."""
    start = int(setup["trigger"]["close_time"])
    escape = max(setup["trigger"]["close"], setup["entry_max"]) * (1 + V2_ESCAPE_PCT / 100)
    for bar in path:
        if bar["time"] <= start or bar["close_time"] >= now_ms:
            continue
        if bar["low"] <= setup["stop"]:
            return "触发后已触及止损位"
        if bar["high"] > escape:
            return f"触发后价格已上冲 {V2_ESCAPE_PCT:.2f}% 以上，不追价"
    return None


def build_signal(setup: dict, ctx: dict, env: dict, ask: float, now_ms: int, book: dict,
                 derivatives: Optional[dict] = None) -> dict:
    meta = MODULES[setup["module"]]
    m = _metrics(ask, setup["stop"], setup["tp1"])
    tp2 = _tp2(setup, ctx)
    trigger = setup["trigger"]
    confirmation = int(trigger["close_time"])
    expires = confirmation + meta["valid_ms"]
    key = f"BTCUSDT_{setup['module']}_{setup['anchor_time']}"
    size_pct = position_fraction_pct(m["risk"])
    breakeven = ask * (1 + V2_FRICTION_PCT / 100)
    scored = score_confirmation(derivatives)
    deriv_note = f"衍生品加分：{tag_text(scored['tags'])}。" if scored["tags"] else ""
    name = f"BTC {meta['name']}"
    until = datetime.fromtimestamp(expires / 1000, CST).strftime("%H:%M")
    widened = "，结构止损过近已放宽到最小距离" if "structural_stop" in setup else ""
    reason = (f"{setup['reason']}。环境：{env['label']}。挂单 {_fmt(setup['entry_min'])}–{_fmt(setup['entry_max'])}，"
              f"止损 {_fmt(setup['stop'])}（-{m['risk']:.2f}%{widened}），TP1 {_fmt(setup['tp1'])} 卖 50% 后止损移到保本，"
              f"余仓跟踪 15m EMA20 或 TP2 {_fmt(tp2)}。扣 {V2_FRICTION_PCT:.2f}% 成本后 TP1 净 {m['net']:.2f}%，"
              f"净盈亏比 {m['rr']:.2f}。{V2_TIME_STOP_MINUTES} 分钟未到 +{V2_TIME_STOP_PROGRESS_R}R 离场，最长 {V2_MAX_HOLD_MINUTES // 60} 小时。"
              f"按账户 {V2_RISK_PER_TRADE_PCT}% 风险，建议仓位约为账户的 {size_pct:.0f}%。有效至 {until}。{deriv_note}{V2_TIER_LABEL}，历史胜率未验证。")
    env_score = max(0, min(40, 20 + env["score"] // 5))
    rr_score = max(0, min(30, int(round((m["rr"] - V2_MIN_NET_RR) * 30))))
    trigger_score = 30
    deriv_score = scored["points"]
    v2 = {
        "module": setup["module"], "tier": V2_TIER_WATCH, "tierLabel": V2_TIER_LABEL,
        "env": {"states": env["states"], "score": env["score"], "gates": env["gates"], "label": env["label"]},
        "features": setup["features"], "tp1Basis": setup["tp1_basis"], "entryRef": setup["entry_ref"],
        "structuralStop": setup.get("structural_stop", setup["stop"]),
        "sessionUtcHour": datetime.fromtimestamp(confirmation / 1000, timezone.utc).hour,
        "spreadPct": round(float(book.get("spread") or 0), 4),
        "derivatives": scored,
    }
    return {
        "symbol": "BTCUSDT", "coin_name": "Bitcoin (比特币)", "signal_type": "BUY", "decision_status": "BUY_CANDIDATE",
        "strategy": meta["strategy"], "model": meta["model"], "rule_version": V2_RULE_VERSION,
        "module": setup["module"], "tier": V2_TIER_WATCH, "tier_label": V2_TIER_LABEL,
        "max_hold_minutes": V2_MAX_HOLD_MINUTES, "min_net_tp1": V2_MIN_NET_TP1, "min_net_rr": V2_MIN_NET_RR,
        "friction_pct": V2_FRICTION_PCT, "max_net_target": None,
        "invalidation_price": round(setup["invalidation"], 2), "tp1_fraction": V2_TP1_FRACTION,
        "target_basis": f"TP1：{setup['tp1_basis']}；TP2：下一结构阻力，余仓跟踪 15m EMA20",
        "exit_rule": (f"跌破止损全部离场；TP1 卖出 50%，止损移到保本（含 {V2_FRICTION_PCT:.2f}% 成本）；余仓在 15m 收盘跌破 EMA20 或到 TP2 离场；"
                      f"{V2_TIME_STOP_MINUTES} 分钟未到 +{V2_TIME_STOP_PROGRESS_R}R 时间止损；持有满 {V2_MAX_HOLD_MINUTES} 分钟离场。"),
        "strategy_name_zh": f"【{V2_TIER_LABEL}】{name}", "entry_price": ask,
        "target_tp1": setup["tp1"], "target_tp2": tp2, "stop_loss": setup["stop"],
        "profit_pct1": round(m["gross"], 4), "profit_pct2": round((tp2 / ask - 1) * 100, 4),
        "stop_loss_pct": round(m["risk"], 4), "net_tp1": round(m["net"], 4),
        "net_tp2": round((tp2 / ask - 1) * 100 - V2_FRICTION_PCT, 4), "net_rr": round(m["rr"], 4),
        "risk_reward": round(m["gross"] / m["risk"], 2) if m["risk"] > 0 else 0,
        "time_horizon": f"5 分钟–{V2_MAX_HOLD_MINUTES // 60} 小时；{V2_TIME_STOP_MINUTES} 分钟时间止损",
        "rule_score": env_score + rr_score + trigger_score + deriv_score,
        "rule_score_breakdown": f"环境{env_score}+净盈亏比{rr_score}+形态{trigger_score}+衍生品{deriv_score}",
        "win_rate_status": "历史胜率：未验证", "reason_zh": reason,
        "structure_support": setup["stop"], "structure_key": key, "alert_id": key,
        "effective_drop": setup["features"].get("dropPct", 0.0), "volatility_level": None, "quantile_pct": None,
        "regime": {"UP": "BULLISH", "DOWN": "BEARISH"}.get(env["states"]["h1"], "RANGING"),
        "hourly_rsi": round(ctx["h1"]["rsi14"], 2), "confirmation_time": confirmation, "timestamp": now_ms,
        "entry_min": round(setup["entry_min"], 2), "entry_max": round(setup["entry_max"], 2), "expires_at": expires,
        "breakout_level": setup.get("breakout_level"), "rsi14": None,
        "atr_percent": None, "volume_multiplier": setup["features"].get("volumeMultiple"),
        "vwap_diff_percent": None, "order_flow_imbalance": round(float(book.get("imbalance") or 0) * 100, 2),
        "breakeven_price": round(breakeven, 2), "time_stop_minutes": V2_TIME_STOP_MINUTES,
        "time_stop_progress_r": V2_TIME_STOP_PROGRESS_R, "trail_rule": "EMA20_15M",
        "position_fraction_pct": round(size_pct, 1), "risk_per_trade_pct": V2_RISK_PER_TRADE_PCT,
        "reclaim_price": round(float(setup["entry_ref"]), 2), "v2": v2,
    }


def context_issue(ctx: Optional[dict], now_ms: int) -> Optional[str]:
    if not ctx or ctx.get("version") != "context-v2":
        return "1D/4H/1H 环境数据尚未就绪"
    if not 0 <= now_ms - int(ctx["atMs"]) <= V2_CONTEXT_MAX_AGE_MS:
        return "1D/4H/1H 环境数据过期"
    if now_ms - int(ctx["h1"]["close_time"]) > 2 * H1 + 60_000:
        return "1H 已收盘 K 线滞后"
    return None


def flush_monitor(m5: List[dict]) -> dict:
    """5m watch only. A flush in progress is reported; it never creates a BUY."""
    if len(m5) < 30:
        return {"active": False}
    low_bar = min(m5[-6:], key=lambda b: b["low"])
    peak = max(b["high"] for b in m5[-144:-1]) if len(m5) > 144 else max(b["high"] for b in m5[:-1])
    drop = (peak - low_bar["low"]) / peak * 100 if peak else 0.0
    base = _avg_volume(m5[-26:-6])
    return {
        "active": drop >= 1.5 and low_bar["volume"] >= 2 * base,
        "dropPct": round(drop, 2),
        "low": low_bar["low"],
        "volumeMultiple": round(low_bar["volume"] / base, 2) if base else None,
    }


def scan(m15: List[dict], m5: List[dict], path: List[dict], ask: float, book: dict,
         ctx: Optional[dict], now_ms: int, breaker: Optional[dict] = None,
         derivatives: Optional[dict] = None) -> Tuple[Optional[dict], List[str], dict]:
    """Returns (signal, reasons, view). A signal needs a fresh setup and the ask inside its band."""
    issue = context_issue(ctx, now_ms)
    if issue:
        return None, [issue], {}
    if not m15:
        return None, ["15m 已收盘 K 线缺失"], {}
    env = environment(ctx, m15[-1]["close"], now_ms)
    scored = score_confirmation(derivatives)
    research = []
    for back in (1, 2):
        if len(m15) < back:
            break
        window = m15[:len(m15) - back + 1]
        if now_ms - int(window[-1]["close_time"]) > 2 * M15:
            continue
        found = detect_s5(window, ctx.get("s5VolumeBaseline"))
        if found:
            research.append(found)
            break
    live_env = environment(ctx, ask, now_ms)
    view = {"env": env, "displayEnv": {"states": live_env["states"], "score": live_env["score"], "label": live_env["label"]},
            "candidates": [], "research": research, "flushMonitor": flush_monitor(m5),
            "derivatives": scored, "levels": [
                {"name": "日线 EMA99", "price": round(float(ctx["d1"]["ema99"]), 2)},
                {"name": "4H EMA99", "price": round(float(ctx["h4"]["ema99"]), 2)},
                {"name": "4H 中轨", "price": round(float(ctx["h4"]["boll_mid"]), 2)},
                {"name": "1H EMA25", "price": round(float(ctx["h1"]["ema25"]), 2)},
            ]}
    reasons = [f"环境：{env['label']}"] + env["closed"]
    if research:
        reasons.append(research[0]["reason"])
    if breaker and now_ms < int(breaker.get("pausedUntil") or 0):
        until = datetime.fromtimestamp(int(breaker["pausedUntil"]) / 1000, CST).strftime("%H:%M")
        reasons.append(f"交易级暂停至 {until}（{breaker.get('reason', '连续止损')}）；观察级继续推送")
        view["tradePausedUntil"] = int(breaker["pausedUntil"])
    if float(book.get("spread") or 999) > 0.02:
        return None, reasons + ["买卖价差超过 0.02%"], view
    attempts = []
    for back in (1, 2):
        if len(m15) < back:
            break
        bars = m15[:len(m15) - back + 1]
        if now_ms - int(bars[-1]["close_time"]) > 2 * M15:
            continue
        for module, detect in (("S1", detect_s1), ("S2", detect_s2), ("S4", detect_s4)):
            if env["gates"][module]:
                attempts.append((module, detect(bars, ctx, env)))
    if env["gates"]["S3"]:
        for back in (1, 2):
            bars5 = m5[:len(m5) - back + 1] if len(m5) >= back else []
            if bars5 and now_ms - int(bars5[-1]["close_time"]) <= 2 * M5:
                bars15 = [b for b in m15 if b["close_time"] <= bars5[-1]["close_time"]]
                attempts.append(("S3", detect_s3(bars5, bars15, ctx, env)))
    for module, setup in attempts:
        if not setup:
            continue
        name = MODULES[module]["name"]
        if setup.get("blocked"):
            reasons.append(f"{module} {name}：{setup['blocked']}")
            view["candidates"].append({"module": module, "name": name, "issue": setup["blocked"]})
            continue
        setup = widen_stop(setup)
        problem = plan_issue(setup) or path_issue(setup, path, now_ms)
        if not problem and not setup["entry_min"] <= ask <= setup["entry_max"]:
            problem = f"当前卖一价 {_fmt(ask)} 不在挂单区间 {_fmt(setup['entry_min'])}–{_fmt(setup['entry_max'])}"
        view["candidates"].append({"module": module, "name": name, "issue": problem,
                                   "entryMin": setup["entry_min"], "entryMax": setup["entry_max"],
                                   "stop": setup["stop"], "tp1": setup["tp1"],
                                   "confirmationTime": int(setup["trigger"]["close_time"])})
        if problem:
            reasons.append(f"{module} {name}：{problem}")
            continue
        return build_signal(setup, ctx, env, ask, now_ms, book, derivatives), reasons, view
    if not view["candidates"]:
        reasons.append("最近两根 15m 没有满足 S1/S2 形态")
    return None, reasons, view
