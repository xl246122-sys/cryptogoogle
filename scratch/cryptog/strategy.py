import math
from typing import Dict, List, Optional, Tuple
from .clock import clock as time
from .config import *
from .features import TechnicalIndicators, get_closed_candles
from .market_state import diagnose_cascade_downtrend
from .cost_risk import entry_contract, model_targets
from .diagnostics import reject as log_skip


def validate_market_data_quality(candles: List[dict], ticker: dict, order_book: dict, hourly_candles: Optional[List[dict]] = None) -> Tuple[bool, str]:
    if not ticker or ticker.get("price", 0) <= 0 or math.isnan(ticker.get("price", 0)):
        return False, "Ticker 价格无效或为0"

    if not order_book or not order_book.get("is_valid", False) or order_book.get("spread", 999.0) > 0.02:
        return False, f"买卖盘口点差异常 ({order_book.get('spread', 999.0):.3f}% > 0.02%) 或盘口不可用"

    if not candles or len(candles) < 20:
        return False, f"1m K线数据不足 (当前仅 {len(candles) if candles else 0} 根，要求 >= 20)"

    for i, c in enumerate(candles):
        if c["low"] <= 0 or c["high"] <= 0 or c["open"] <= 0 or c["close"] <= 0:
            return False, "存在异常价格 <= 0"
        if c["high"] < max(c["open"], c["close"]) or c["low"] > min(c["open"], c["close"]):
            return False, "K线结构不合法 (High < max(Open,Close) 或 Low > min(Open,Close))"
        if i > 0 and c["time"] <= candles[i - 1]["time"]:
            return False, "K线时间戳非严格单调递增"

    atr14 = TechnicalIndicators.atr(candles, 14)
    if atr14 <= 0 or math.isnan(atr14):
        return False, "ATR(14) 指标无效或为0"

    if not hourly_candles or len(hourly_candles) < 15:
        return False, "缺少 1H 宏观行情K线"

    latest_1h = hourly_candles[-1]
    now_ms = int(time.time() * 1000)
    age_hours = (now_ms - latest_1h.get("close_time", latest_1h.get("time", 0))) / (1000 * 3600)
    if age_hours > 2.0:
        return False, f"1H 宏观行情数据滞后 ({age_hours:.1f}小时 > 2小时)"

    for i in range(1, len(candles)):
        gap = candles[i]["time"] - candles[i - 1]["time"]
        if gap > 10 * 60 * 1000:
            return False, "1m K线存在超过10分钟的缺口"

    return True, "数据质量门禁通过"



def verify_micro_range_reversal(closed_candles: List[dict], order_book: dict, ticker: dict) -> Tuple[bool, str, float, float]:
    if not closed_candles or len(closed_candles) < 15:
        return False, "已收盘K线数据不足", 0.0, 0.0

    curr_price = ticker["price"]
    latest = closed_candles[-1]
    prev = closed_candles[-2]
    prev_prev = closed_candles[-3]
    closes = [c["close"] for c in closed_candles]
    ema7 = TechnicalIndicators.ema(closes, 7)

    recent_lows = [c["low"] for c in closed_candles[-14:]]
    recent_highs = [c["high"] for c in closed_candles[-14:]]
    supp_price = min(recent_lows)
    res_price = max(recent_highs)

    # Barrier 1: Local low stops making lower lows
    is_low_ceased = (latest["low"] >= prev["low"] * 0.9995 and
                     latest["low"] >= min(prev["low"], prev_prev["low"]) * 0.9990)
    if not is_low_ceased:
        return False, "【门禁1拦截】局部低点仍在破位下移", supp_price, res_price

    # Barrier 2: Decisive structural reclaim
    # Correct Candlestick Body Midpoint Formula
    if prev["close"] < prev["open"]:
        prev_mid = (prev["open"] + prev["close"]) / 2.0
    else:
        prev_mid = (prev["high"] + prev["low"]) / 2.0

    c_range = latest["high"] - latest["low"]
    body = latest["close"] - latest["open"]
    is_solid_green = body >= (c_range * 0.12 if c_range > 0 else 0) and latest["close"] >= latest["open"]
    is_above_ema7 = latest["close"] >= ema7 * 0.9995
    is_above_mid = latest["close"] >= prev_mid * 0.9998

    if not (is_solid_green and is_above_ema7 and is_above_mid):
        return False, "【门禁2拦截】未站稳EMA7或未收复前K实体中轴", supp_price, res_price

    # Barrier 3: executed taker-buy on the closed candle, plus a non-dump volume check.
    # Resting bid size alone is not treated as completed buying.
    recent_vols = [c["volume"] for c in closed_candles[-6:-1]]
    avg_vol = sum(recent_vols) / max(1, len(recent_vols))
    is_vol_controlled = latest["volume"] <= avg_vol * 2.4
    taker = float(latest.get("taker_buy_base", 0.0) or 0.0)
    taker_ratio = taker / latest["volume"] if latest["volume"] > 0 else 0.0
    has_executed_buy = taker_ratio >= 0.52
    has_imb = order_book.get("imbalance", 0.0) >= 0.02

    if not (has_executed_buy and has_imb and is_vol_controlled):
        return False, "【门禁3拦截】已收盘主动买量不足(52%)、挂单失衡不足或下杀未缩量", supp_price, res_price

    # Barrier 4: Spread normality
    spread = order_book.get("spread", 0.01)
    if spread > 0.02:
        return False, f"【门禁4拦截】买卖价差异常({spread:.3f}% > 0.02%)", supp_price, res_price

    return True, "5重微波段止跌企稳门禁全部通过", supp_price, res_price



def _closed_breakout(closed_5m: List[dict], closed_15m: List[dict], now_ms: Optional[int] = None) -> Optional[dict]:
    """A finished 5m or 15m candle closing through the prior high. Not an intra-bar spike."""
    now_ms = int(time.time() * 1000) if now_ms is None else now_ms
    def _one(candles: List[dict], lookback: int, label: str, need_ema_stack: bool) -> Optional[dict]:
        if not candles or len(candles) < lookback + 2:
            return None
        last = candles[-1]
        confirmed = last.get("close_time", 0)
        if not 0 <= now_ms - confirmed < SETUP_MAX_AGE_MS:
            return None
        window = candles[-(lookback + 1):-1]
        prior = max(c["high"] for c in window)
        closes = [c["close"] for c in candles]
        ema7 = TechnicalIndicators.ema(closes, 7)
        ema25 = TechnicalIndicators.ema(closes, 25)
        vols = [c["volume"] for c in window]
        avg = sum(vols) / len(vols) if vols else 0.0
        span = last["high"] - last["low"]
        wick = ((last["high"] - last["close"]) / span) if span > 0 else 1.0
        taker = float(last.get("taker_buy_base") or 0.0)
        taker_ratio = taker / last["volume"] if last["volume"] else 0.0
        stacked = (not need_ema_stack) or (ema7 >= ema25 * 0.998)
        if (
            last["close"] >= last["open"]
            and prior > 0
            and last["close"] > prior
            and ema7 > 0
            and last["close"] >= ema7 * 0.999
            and stacked
            and avg > 0 and last["volume"] >= avg * 1.08
            and wick <= 0.45
            and taker_ratio >= 0.48
        ):
            return {
                "low": last["low"],
                "close_time": last.get("close_time", last.get("time", 0)),
                "label": label,
                "prior": prior,
                "close": last["close"],
            }
        return None

    return _one(closed_5m, 12, "5m", False) or _one(closed_15m, 8, "15m", True)



def observed_resistances(*series: List[dict]) -> List[float]:
    """Confirmed local highs: two already-closed bars on either side, no future bars."""
    levels = []
    for bars in series:
        for i in range(2, len(bars) - 2):
            high = bars[i]["high"]
            neighbours = [bars[j]["high"] for j in (i-2, i-1, i+1, i+2)]
            if high >= max(neighbours) and high > min(neighbours):
                levels.append(high)
    return sorted(set(levels))



def stable_range_box(bars: List[dict], entry: float) -> Optional[dict]:
    """Require repeat boundary tests and low directional efficiency, not merely 'not bullish'."""
    if len(bars) < 32:
        return None
    window = bars[-32:]
    low, high = min(c['low'] for c in window), max(c['high'] for c in window)
    width = high - low
    if low <= 0 or width <= 0 or not low < entry <= low + width * 0.25:
        return None
    closes = [c['close'] for c in window]
    travel = sum(abs(b-a) for a, b in zip(closes, closes[1:]))
    if travel <= 0 or abs(closes[-1]-closes[0]) / travel > 0.35:
        return None
    left, right = window[:16], window[16:]
    if abs(min(c['low'] for c in left)-min(c['low'] for c in right)) > width * 0.20:
        return None
    if abs(max(c['high'] for c in left)-max(c['high'] for c in right)) > width * 0.20:
        return None
    def touches(side):
        indices = [i for i,c in enumerate(window) if (c['low'] <= low+width*.10 if side == 'low' else c['high'] >= high-width*.10)]
        selected = []
        for i in indices:
            if not selected or i-selected[-1] >= 3: selected.append(i)
        return len(selected)
    if touches('low') < 2 or touches('high') < 2:
        return None
    return {'low': low, 'high': high, 'mid': (low+high)/2}



def recent_crash_confirmed(bars: List[dict]) -> bool:
    if len(bars) < 12:
        return False
    # Peak precedes trough. 12 x 5m = one hour; a slow 24h decline is insufficient.
    peak = max(c['high'] for c in bars[-12:-4])
    trough = min(c['low'] for c in bars[-4:])
    return peak > 0 and (peak-trough)/peak * 100 >= 3.0



def scan_symbol(symbol: str, ticker: dict, macro: dict, raw_candles: List[dict], order_book: dict, hourly_candles: Optional[List[dict]] = None, regime_candles: Optional[List[dict]] = None, five_min_candles: Optional[List[dict]] = None) -> Optional[dict]:
    if symbol != "BTCUSDT":
        log_skip('标的不是 BTCUSDT')
        return None
    if macro.get("trend") == "INSUFFICIENT":
        log_skip('宏观行情不足')
        return None

    # Step 1: Validate Market Data Quality Gate
    is_valid, quality_reason = validate_market_data_quality(raw_candles, ticker, order_book, hourly_candles)
    if not is_valid:
        log_skip(quality_reason)
        return None

    # Step 2: Extract Confirmed Closed Candles (Intra-bar confirmation fix)
    closed_candles = get_closed_candles(raw_candles)
    if not closed_candles or len(closed_candles) < 16:
        log_skip('1m 已收盘样本不足')
        return None

    curr_price = ticker["price"]
    closes = [c["close"] for c in closed_candles]
    latest_closed = closed_candles[-1]
    confirmation_time = latest_closed.get("close_time", latest_closed.get("time", 0))

    sma20, std20, upper_bb, lower_bb, vwap = TechnicalIndicators.vwap_and_bands(closed_candles, 20)
    rsi14 = TechnicalIndicators.rsi(closed_candles, 14)
    atr14 = TechnicalIndicators.atr(closed_candles, 14)

    # Waterfall check on closed candles
    is_cascading, cascade_reason = diagnose_cascade_downtrend(closed_candles, ticker)
    if is_cascading:
        log_skip(cascade_reason or "瀑布通道拦截")
        return None

    # Peak & Drop Calculation
    candle_high = max(c["high"] for c in closed_candles)
    peak_price = max(ticker.get("high24h", curr_price), candle_high, curr_price)
    drop_from_peak = ((peak_price - curr_price) / peak_price) * 100 if peak_price > 0 else 0.0
    net_drop_24h = abs(ticker["change24h"]) if ticker["change24h"] < 0 else 0.0
    effective_drop = max(drop_from_peak, net_drop_24h)

    is_bearish = macro.get("is_bearish", False) or ticker["change24h"] < -1.5

    closed_regime = get_closed_candles(regime_candles or [])
    if len(closed_regime) < 64:
        log_skip("15m 样本不足，无法估计短线波动")
        return None

    vol_regime = TechnicalIndicators.calculate_volatility_regime(closed_regime, curr_price)
    if vol_regime.get("level") not in ("LOW", "MEDIUM", "HIGH"):
        log_skip("15m 波动分级无效")
        return None

    closed_5m = get_closed_candles(five_min_candles or [])
    fresh_now = int(time.time() * 1000)
    for bars, interval in ((closed_candles, 60_000), (closed_regime, 900_000),
                           (closed_5m, 300_000), (get_closed_candles(hourly_candles or []), 3_600_000)):
        if not bars or not 0 <= fresh_now - bars[-1].get("close_time", 0) <= interval + QUOTE_MAX_AGE_MS:
            log_skip("已收盘行情缺失或过期，暂停生成候选")
            return None
    breakout = _closed_breakout(closed_5m, closed_regime)
    # A failed current-price breakout cannot be relabelled as a pullback in the same scan.
    if breakout and curr_price <= breakout["prior"]:
        log_skip('确认突破后价格已跌回突破位')
        return None
    strong_bear = bool(macro.get("is_strongly_bearish")) and curr_price < float(macro.get("ma20") or curr_price)

    passed_reversal, rev_reason, supp_p, res_p = verify_micro_range_reversal(closed_candles, order_book, ticker)

    recent_lows = [c["low"] for c in closed_candles[-14:]]
    swing_bottom = min(recent_lows)
    bounce_pct = ((curr_price - swing_bottom) / swing_bottom) * 100
    ema7 = TechnicalIndicators.ema(closes, 7)

    is_bottom_rebound = (
        0.20 <= bounce_pct <= 1.8 and
        latest_closed["close"] >= latest_closed["open"] and
        curr_price >= ema7 * 0.9985 and
        32 <= rsi14 <= 62 and
        order_book["imbalance"] >= 0.02
    )

    rsi_div = TechnicalIndicators.detect_rsi_divergence(closed_candles, 14)

    resistance_levels = observed_resistances(closed_regime, get_closed_candles(hourly_candles or []))
    model = None
    reference_price = latest_closed["close"]
    invalidation_price = 0.0
    structure_support = 0.0
    if breakout and not strong_bear:
        model = "BREAKOUT"
        matched_strategy = "BURST_BREAKOUT"
        strategy_name_zh = f"BTC {breakout['label']}确认突破"
        confirmation_time = breakout["close_time"]
        reference_price = breakout["close"]
        structure_support = breakout["low"]
        invalidation_price = max(structure_support, breakout["prior"])
        reason_zh = f"已收盘{breakout['label']}突破前高 ${breakout['prior']:,.2f}；跌回该位即失效。"
    elif is_bearish:
        if effective_drop < MIN_BEARISH_DROP_REQUIRED or not recent_crash_confirmed(closed_5m):
            peak = max(c['high'] for c in closed_5m[-12:-4]) if len(closed_5m)>=12 else 0
            trough = min(c['low'] for c in closed_5m[-4:]) if peak else 0
            recent_drop = (peak-trough)/peak*100 if peak else 0
            log_skip(f"急跌反弹未准入：累计跌幅{effective_drop:.2f}%（要求≥5%）；近1小时先高后低跌幅{recent_drop:.2f}%（要求≥3%）")
            return None
        if not passed_reversal or not (is_bottom_rebound or rsi_div):
            log_skip(rev_reason if not passed_reversal else "暴跌后尚未出现右侧反转确认")
            return None
        model = "REBOUND"
        matched_strategy = "FLASH_CRASH_REBOUND"
        strategy_name_zh = "BTC 暴跌后右侧反弹"
        structure_support = math.floor((min(supp_p, swing_bottom)-0.25*atr14)*100)/100
        invalidation_price = min(supp_p, swing_bottom)
        reason_zh = "累计跌幅和近1小时急跌同时满足，瀑布过滤及微观止跌门禁通过；不代表已经见底。"
        # Nearby recovery barriers are binding; a farther target cannot hide them.
        resistance_levels += [res_p]
    elif macro.get("trend") == "RANGING":
        box = stable_range_box(closed_regime, curr_price)
        if not box or not passed_reversal or rsi14 > 48:
            log_skip("箱体不稳定或未在下沿" if not box else rev_reason if not passed_reversal else "区间 RSI 高于48，入场过晚")
            return None
        model = "RANGE"
        matched_strategy = "RANGE_OSCILLATION"
        strategy_name_zh = f"BTC 区间低吸 ({vol_regime['level']})"
        structure_support = math.floor((min(box['low'], supp_p)-0.25*atr14)*100)/100
        invalidation_price = box['low']
        reason_zh = "15m箱体上下沿重复测试、方向效率受限；下沿四分之一区域通过五类止跌过滤。跌破箱底即失效。"
        resistance_levels += [box['mid'], box['high'], res_p]
    else:
        log_skip('当前背景下无已确认突破；没有启用独立回踩买入路径')
        return None  # No independent pullback, RSI-only or VWAP-only BUY paths.

    policy = TRADE_POLICIES[model]
    targets = model_targets(model, curr_price, structure_support, resistance_levels)
    if not targets or not structure_support <= invalidation_price < curr_price:
        log_skip(f"{strategy_name_zh}最近阻力空间不足或结构止损不合格，放弃交易")
        return None
    time_horizon = f"最长 {policy['max_hold_minutes']} 分钟；止损/失效优先，不强制持有10分钟"
    sl = targets["sl"]
    tp1 = targets["tp1"]
    tp2 = targets["tp2"]
    net_tp1 = targets["net_tp1"]
    net_tp2 = targets["net_tp2"]
    net_rr = targets["net_rr"]
    target_tp1 = targets["target_tp1"]
    target_tp2 = targets["target_tp2"]
    stop_loss = targets["stop_loss"]
    structure_support = targets["support"]
    generated_ms = int(time.time() * 1000)
    contract = entry_contract(curr_price, target_tp1, stop_loss, confirmation_time,
                              breakout["prior"] if matched_strategy == "BURST_BREAKOUT" else None,
                              generated_ms, reference_price, policy["min_net_tp1"], invalidation_price)
    if contract is None:
        log_skip("信号已过期或入场价格不满足有效区间/净收益门禁")
        return None
    volume_baseline = sum(c["volume"] for c in closed_candles[-21:-1]) / len(closed_candles[-21:-1])

    taker_base = float(latest_closed.get("taker_buy_base") or 0.0)
    taker_ratio = taker_base / latest_closed["volume"] if latest_closed["volume"] > 0 else 0.0
    candle_range = latest_closed["high"] - latest_closed["low"]
    body_ratio = (latest_closed["close"] - latest_closed["open"]) / candle_range if candle_range > 0 else 0.0
    body_pts = max(0, min(25, int(round(body_ratio * 25))))
    taker_pts = max(0, min(40, int(round(taker_ratio * 40))))
    rr_pts = max(0, min(35, int(round((net_rr - MIN_NET_RR) * 25))))
    rule_score = max(0, min(100, body_pts + taker_pts + rr_pts))
    rule_breakdown = f"实体{body_pts}+主动买量{taker_pts}+净盈亏比{rr_pts}"
    reason_zh = (
        f"{reason_zh} 止损在已收盘结构低点 ${structure_support:,.2f}，"
        f"目标来源：{targets['target_basis']}。"
        f"规则分项：{rule_breakdown}。这不是上涨概率。历史胜率：未验证。"
    )

    return {
        "symbol": "BTCUSDT",
        "coin_name": "Bitcoin (比特币)",
        "signal_type": "BUY",
        "decision_status": "BUY_CANDIDATE",
        "strategy": matched_strategy,
        "model": model,
        "rule_version": RULE_VERSION,
        "max_hold_minutes": policy["max_hold_minutes"],
        "min_net_tp1": policy["min_net_tp1"],
        "max_net_target": policy["max_net_target"],
        "invalidation_price": invalidation_price,
        "tp1_fraction": targets["tp1_fraction"],
        "target_basis": targets["target_basis"],
        "exit_rule": "价格触及止损或失效位退出剩余仓位；TP1按比例退出，余仓TP2退出；到期退出剩余仓位。止损不自动上移。",
        "strategy_name_zh": strategy_name_zh,
        "entry_price": curr_price,
        "target_tp1": target_tp1,
        "target_tp2": target_tp2,
        "stop_loss": stop_loss,
        "profit_pct1": tp1,
        "profit_pct2": tp2,
        "stop_loss_pct": sl,
        "net_tp1": net_tp1,
        "net_tp2": net_tp2,
        "net_rr": net_rr,
        "risk_reward": round(tp1 / sl, 2),
        "time_horizon": time_horizon,
        "rule_score": rule_score,
        "rule_score_breakdown": rule_breakdown,
        "win_rate_status": "历史胜率：未验证",
        "reason_zh": reason_zh,
        "structure_support": structure_support,
        "effective_drop": effective_drop,
        "volatility_level": vol_regime["level"],
        "quantile_pct": vol_regime["quantile"],
        "regime": macro.get("trend", "UNKNOWN"),
        "hourly_rsi": round(float(macro.get("rsi") or 0.0), 2),
        "confirmation_time": confirmation_time,
        "timestamp": generated_ms,
        **contract,
        "rsi14": round(rsi14, 2),
        "atr_percent": round(atr14 / curr_price * 100, 4),
        "volume_multiplier": round(latest_closed["volume"] / volume_baseline, 4) if volume_baseline > 0 else None,
        "vwap_diff_percent": round((curr_price / vwap - 1) * 100, 4) if vwap > 0 else None,
        "order_flow_imbalance": round(order_book["imbalance"] * 100, 2),
    }

