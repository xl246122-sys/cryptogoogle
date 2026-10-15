# Frozen from audited V1.12; only declarations, executed by the parity test.
def get_closed_candles(candles: List[dict]) -> List[dict]:
    """
    Returns only confirmed closed candles.
    Excludes forming intra-bar candle to eliminate false breakout signals.
    """
    if not candles:
        return []
    now_ms = int(time.time() * 1000)
    closed = [c for c in candles if c.get("is_closed", False) or c.get("close_time", 0) <= now_ms]
    if closed and closed[-1].get("close_time", 0) > now_ms:
        closed = closed[:-1]
    elif not closed and len(candles) > 1:
        closed = candles[:-1]
    return closed

class TechnicalIndicators:
    @staticmethod
    def sma(values: List[float], period: int) -> float:
        if len(values) < period:
            return values[-1] if values else 0.0
        return sum(values[-period:]) / period

    @staticmethod
    def ema(values: List[float], period: int) -> float:
        if not values:
            return 0.0
        if len(values) < period:
            return TechnicalIndicators.sma(values, len(values))
        k = 2.0 / (period + 1.0)
        ema_val = values[0]
        for v in values[1:]:
            ema_val = v * k + ema_val * (1.0 - k)
        return ema_val

    @staticmethod
    def rsi(candles: List[dict], period: int = 14) -> float:
        if len(candles) < period + 1:
            return 50.0
        closes = [c["close"] for c in candles]
        gains = []
        losses = []
        for i in range(len(closes) - period, len(closes)):
            diff = closes[i] - closes[i - 1]
            if diff >= 0:
                gains.append(diff)
                losses.append(0.0)
            else:
                gains.append(0.0)
                losses.append(-diff)
        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return round(100.0 - (100.0 / (1.0 + rs)), 2)

    @staticmethod
    def atr(candles: List[dict], period: int = 14) -> float:
        if len(candles) < period + 1:
            return 0.0
        trs = []
        for i in range(len(candles) - period, len(candles)):
            curr = candles[i]
            prev_close = candles[i - 1]["close"]
            tr = max(curr["high"] - curr["low"], abs(curr["high"] - prev_close), abs(curr["low"] - prev_close))
            trs.append(tr)
        return sum(trs) / len(trs) if trs else 0.0

    @staticmethod
    def quantile(values: List[float], percentile: float) -> float:
        if not values:
            return 0.0
        s = sorted(values)
        idx = (percentile / 100.0) * (len(s) - 1)
        low = int(math.floor(idx))
        high = int(math.ceil(idx))
        weight = idx - low
        if high == low:
            return s[low]
        return round(s[low] * (1.0 - weight) + s[high] * weight, 3)

    @staticmethod
    def vwap_and_bands(candles: List[dict], period: int = 20):
        closes = [c["close"] for c in candles]
        highs = [c["high"] for c in candles]
        lows = [c["low"] for c in candles]
        volumes = [c["volume"] for c in candles]

        sub_closes = closes[-period:]
        sma20 = sum(sub_closes) / len(sub_closes)
        var = sum((x - sma20) ** 2 for x in sub_closes) / len(sub_closes)
        std20 = math.sqrt(var)

        cum_vol = sum(volumes[-period:])
        cum_pv = sum(((highs[i] + lows[i] + closes[i]) / 3.0) * volumes[i] for i in range(len(closes) - period, len(closes)))
        vwap = cum_pv / cum_vol if cum_vol > 0 else sma20

        return sma20, std20, sma20 + 2 * std20, sma20 - 2 * std20, vwap

    @staticmethod
    def calculate_rolling_swing_range(candles: List[dict], window_bars: int = 16) -> Tuple[List[float], float]:
        """
        Calculates uniform rolling window swing ranges across session bars.
        Eliminates the statistical discrepancy of comparing 24-bar cumulative swings
        against single-bar ranges.
        """
        if len(candles) < window_bars:
            return [1.0], 1.0

        historical_swings = []
        for i in range(window_bars, len(candles) + 1):
            sub = candles[i - window_bars:i]
            sub_high = max(c["high"] for c in sub)
            sub_low = min(c["low"] for c in sub)
            sw = round(((sub_high - sub_low) / sub_low) * 100.0, 3) if sub_low > 0 else 0.0
            historical_swings.append(sw)

        recent_sub = candles[-window_bars:]
        recent_high = max(c["high"] for c in recent_sub)
        recent_low = min(c["low"] for c in recent_sub)
        active_swing = round(((recent_high - recent_low) / recent_low) * 100.0, 2) if recent_low > 0 else 1.0

        return historical_swings, active_swing

    @staticmethod
    def calculate_volatility_regime(candles: List[dict], current_price: float) -> dict:
        """
        Volatility on the candle series passed in. Production must pass 15m bars, not 1m bars.
        The current window is excluded from the reference distribution.
        LOW requires quantile <= 30 and swing <= P25. A small ATR cannot force LOW.
        ATR% >= 0.48 or swing >= 2.5 forces HIGH.
        """
        if not candles or len(candles) < 16:
            return {
                "level": "MEDIUM",
                "name": "中度波动 (标准箱体震荡)",
                "tp1": 1.35,
                "tp2": 2.80,
                "sl": 0.85,
                "swing": 1.2,
                "quantile": 50,
                "p25": 0.85,
                "p75": 1.75
            }

        # Calculate uniform rolling swing ranges with W=16
        historical_ranges, swing_pct = TechnicalIndicators.calculate_rolling_swing_range(candles, 16)
        history = historical_ranges[:-1] if len(historical_ranges) > 1 else historical_ranges

        p25 = TechnicalIndicators.quantile(history, 25)
        p50 = TechnicalIndicators.quantile(history, 50)
        p75 = TechnicalIndicators.quantile(history, 75)

        lower_count = sum(1 for r in history if r <= swing_pct)
        quantile_pct = int(round((lower_count / len(history)) * 100)) if history else 50

        closes = [c["close"] for c in candles]
        sma20 = sum(closes[-20:]) / min(20, len(closes))
        std20 = math.sqrt(sum((x - sma20) ** 2 for x in closes[-20:]) / min(20, len(closes)))
        bandwidth = round(((std20 * 4) / sma20) * 100, 2) if sma20 > 0 else 1.2

        atr14 = TechnicalIndicators.atr(candles, 14)
        atr_pct = round((atr14 / current_price) * 100, 4) if current_price > 0 else 0.0

        # LOW only when the relative rank is actually low. A tiny ATR must not override a high rank.
        is_absolute_high = atr_pct >= 0.48 or swing_pct >= 2.5
        is_low_vol = (not is_absolute_high) and quantile_pct <= 30 and swing_pct <= p25
        is_high_vol = is_absolute_high or quantile_pct >= 75

        if is_low_vol:
            tp1 = max(0.65, round(atr_pct * 1.6, 2))
            tp2 = max(1.25, round(atr_pct * 3.0, 2))
            sl = min(0.65, max(0.38, round(atr_pct * 1.1, 2)))
            return {
                "level": "LOW",
                "name": "小幅度波动 (窄幅小波段)",
                "tp1": tp1,
                "tp2": tp2,
                "sl": sl,
                "swing": swing_pct,
                "quantile": quantile_pct,
                "p25": p25,
                "p75": p75,
                "sample_bars": len(candles),
                "atr_pct": atr_pct,
            }
        elif is_high_vol:
            tp1 = max(1.85, round(atr_pct * 2.6, 2))
            tp2 = max(3.80, round(atr_pct * 4.8, 2))
            sl = min(1.45, max(0.95, round(atr_pct * 1.6, 2)))
            return {
                "level": "HIGH",
                "name": "大幅度波动 (宽幅拉锯震荡)",
                "tp1": tp1,
                "tp2": tp2,
                "sl": sl,
                "swing": swing_pct,
                "quantile": quantile_pct,
                "p25": p25,
                "p75": p75,
                "sample_bars": len(candles),
                "atr_pct": atr_pct,
            }
        else:
            tp1 = max(1.20, round(atr_pct * 2.1, 2))
            tp2 = max(2.60, round(atr_pct * 3.8, 2))
            sl = min(0.95, max(0.60, round(atr_pct * 1.3, 2)))
            return {
                "level": "MEDIUM",
                "name": "中度波动 (标准箱体震荡)",
                "tp1": tp1,
                "tp2": tp2,
                "sl": sl,
                "swing": swing_pct,
                "quantile": quantile_pct,
                "p25": p25,
                "p75": p75,
                "sample_bars": len(candles),
                "atr_pct": atr_pct,
            }

    @staticmethod
    def detect_rsi_divergence(candles: List[dict], period: int = 14) -> Optional[dict]:
        if len(candles) < period + 10:
            return None
        closes = [c["close"] for c in candles]
        lows = [c["low"] for c in candles]

        rsi_series = []
        for i in range(period, len(candles)):
            sub = candles[:i + 1]
            r = TechnicalIndicators.rsi(sub, period)
            rsi_series.append({"low": lows[i], "rsi": r, "close": closes[i], "candle": candles[i]})

        if len(rsi_series) < 8:
            return None

        split = max(2, int(len(rsi_series) * 0.55))
        earlier = rsi_series[:split]
        recent = rsi_series[split:]

        min_earlier = min(earlier, key=lambda x: x["low"])
        min_recent = min(recent, key=lambda x: x["low"])

        latest = candles[-1]
        is_green = latest["close"] >= latest["open"] * 0.9995
        has_bounced = closes[-1] >= min_recent["low"] * 1.002

        if not (is_green and has_bounced):
            return None

        if (min_recent["low"] <= min_earlier["low"] * 1.0015 and
                min_recent["rsi"] >= min_earlier["rsi"] + 2.0 and
                min_recent["rsi"] <= 42.0):
            return {
                "price_low1": min_earlier["low"],
                "price_low2": min_recent["low"],
                "rsi_low1": min_earlier["rsi"],
                "rsi_low2": min_recent["rsi"],
                "diff_rsi": round(min_recent["rsi"] - min_earlier["rsi"], 1)
            }
        return None

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

def diagnose_cascade_downtrend(candles: List[dict], ticker: dict) -> Tuple[bool, str]:
    if not candles or len(candles) < 15:
        return False, ""
    closes = [c["close"] for c in candles]
    ema7 = TechnicalIndicators.ema(closes, 7)
    ema25 = TechnicalIndicators.ema(closes, 25)
    curr_price = ticker["price"]

    is_ema_waterfall = ema7 < ema25 and curr_price < ema7 * 0.9985
    recent5 = candles[-5:]
    lower_highs = sum(1 for i in range(1, len(recent5)) if recent5[i]["high"] <= recent5[i - 1]["high"] * 1.0005)

    start12 = closes[max(0, len(closes) - 12)]
    drop_pct = ((curr_price - start12) / start12) * 100

    if (is_ema_waterfall and lower_highs >= 3) or (is_ema_waterfall and ticker["change24h"] < -2.5) or (drop_pct < -0.8 and is_ema_waterfall):
        return True, f"单边空头瀑布 (EMA7 ${ema7:.2f} < EMA25 ${ema25:.2f}, 短线下杀 {drop_pct:.2f}%)"
    return False, ""

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

def entry_contract(entry: float, tp1: float, stop: float, confirmation_ms: int,
                   breakout_level: Optional[float] = None, now_ms: Optional[int] = None,
                   reference_price: Optional[float] = None, min_net_tp1: float = MIN_NET_TP1,
                   invalidation_price: Optional[float] = None) -> Optional[dict]:
    """Bounded entry policy, not a fitted profitability claim. Keep original targets fixed."""
    now_ms = int(time.time() * 1000) if now_ms is None else now_ms
    if not all(math.isfinite(x) and x > 0 for x in (entry, tp1, stop, confirmation_ms)):
        return None
    if not stop < entry < tp1 or not 0 <= now_ms - confirmation_ms < SETUP_MAX_AGE_MS:
        return None
    if breakout_level is not None and (not math.isfinite(breakout_level) or entry <= breakout_level):
        return None
    reference_price = entry if reference_price is None else reference_price
    if not math.isfinite(reference_price) or reference_price <= 0:
        return None
    lower = max(max(entry, reference_price) * (1 - MAX_ENTRY_DEVIATION_PCT / 100), stop * (1 + 1e-8), breakout_level or 0, invalidation_price or 0)
    upper = min(min(entry, reference_price) * (1 + MAX_ENTRY_DEVIATION_PCT / 100),
                tp1 / (1 + (max(MIN_NET_TP1, min_net_tp1) + FRICTION_PCT) / 100),
                (tp1 + MIN_NET_RR * stop) / ((1 + FRICTION_PCT / 100) * (1 + MIN_NET_RR)))
    if not lower <= entry <= upper:
        return None
    return {"entry_min": lower, "entry_max": upper,
            "expires_at": min(now_ms + ALERT_TTL_MS, confirmation_ms + SETUP_MAX_AGE_MS),
            "breakout_level": breakout_level}

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

def model_targets(model: str, entry: float, stop: float, resistances: List[float]) -> Optional[dict]:
    policy = TRADE_POLICIES.get(model)
    if not policy or not all(math.isfinite(x) and x > 0 for x in (entry, stop)) or stop >= entry:
        return None
    risk = (entry-stop)/entry*100
    if risk > policy['max_stop_pct']:
        return None  # Never tighten a structural stop to manufacture R:R.
    barriers = sorted({p for p in resistances if p is not None and math.isfinite(p) and p > entry})
    if not barriers:
        return None  # Including price discovery: no invented ATR target.
    targets = [math.floor(p*(1-TARGET_BUFFER_PCT/100)*100)/100 for p in barriers]
    cap = policy['max_net_target']
    if cap is not None:
        cap_price = math.floor(entry*(1+(cap+FRICTION_PCT)/100)*100)/100
        targets = [min(p, cap_price) for p in targets]  # Cap DOWN, never raise to the minimum.
    first = targets[0]
    second = targets[1] if len(targets) > 1 else first
    if not stop < entry < first <= second:
        return None
    gross = (first/entry-1)*100
    net = gross-FRICTION_PCT
    net_rr = net/(risk+FRICTION_PCT)
    if net < max(MIN_NET_TP1, policy['min_net_tp1']) - 1e-9 or net_rr < MIN_NET_RR - 1e-9:
        return None  # Do not skip the nearest resistance for a more appealing farther one.
    return {'sl': round(risk, 4), 'tp1': round(gross, 4), 'tp2': round((second/entry-1)*100, 4),
            'target_tp1': first, 'target_tp2': second, 'stop_loss': stop,
            'net_tp1': round(net, 4), 'net_tp2': round((second/entry-1)*100-FRICTION_PCT, 4),
            'net_rr': round(net_rr, 4), 'support': stop, 'kind': 'observed_resistance',
            'target_basis': '已确认局部高点/箱体中线等最近阻力前 0.05%；只向下限幅',
            'tp1_fraction': 1.0 if first == second else policy['tp1_fraction']}

def scan_symbol(symbol: str, ticker: dict, macro: dict, raw_candles: List[dict], order_book: dict, hourly_candles: Optional[List[dict]] = None, regime_candles: Optional[List[dict]] = None, five_min_candles: Optional[List[dict]] = None) -> Optional[dict]:
    if symbol != "BTCUSDT":
        return None
    if macro.get("trend") == "INSUFFICIENT":
        return None

    # Step 1: Validate Market Data Quality Gate
    is_valid, quality_reason = validate_market_data_quality(raw_candles, ticker, order_book, hourly_candles)
    if not is_valid:
        log_skip(quality_reason)
        return None

    # Step 2: Extract Confirmed Closed Candles (Intra-bar confirmation fix)
    closed_candles = get_closed_candles(raw_candles)
    if not closed_candles or len(closed_candles) < 16:
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
            log_skip("反弹需累计跌幅≥5%且近1小时先高后低跌幅≥3%；缓慢阴跌不准入")
            return None
        if not passed_reversal or not (is_bottom_rebound or rsi_div):
            log_skip(rev_reason or "暴跌后尚未出现右侧反转确认")
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
            log_skip(rev_reason or "箱体不稳定、未在下沿或缺少右侧止跌")
            return None
        model = "RANGE"
        matched_strategy = "RANGE_OSCILLATION"
        strategy_name_zh = f"BTC 区间低吸 ({vol_regime['level']})"
        structure_support = math.floor((min(box['low'], supp_p)-0.25*atr14)*100)/100
        invalidation_price = box['low']
        reason_zh = "15m箱体上下沿重复测试、方向效率受限；下沿四分之一区域通过五类止跌过滤。跌破箱底即失效。"
        resistance_levels += [box['mid'], box['high'], res_p]
    else:
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