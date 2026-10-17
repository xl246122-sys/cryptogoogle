import math
from typing import Dict, List, Optional, Tuple
from .clock import clock as time
from .config import *
from .features import TechnicalIndicators, get_closed_candles


def live_hourly_reading(closed_bars: Optional[List[dict]], price: Optional[float]) -> Optional[dict]:
    """Display-only 1h RSI and MA20. The last close is the live price, so the card moves during the hour."""
    if not closed_bars or not isinstance(price, (int, float)) or not math.isfinite(price) or price <= 0:
        return None
    closes = []
    for bar in closed_bars:
        close = bar.get("close") if isinstance(bar, dict) else None
        if not isinstance(close, (int, float)) or not math.isfinite(close) or close <= 0:
            return None
        closes.append(float(close))
    if len(closes) < 15:
        return None
    candles = [{"close": close} for close in closes] + [{"close": float(price)}]
    return {
        "liveRsi": TechnicalIndicators.rsi(candles, 14),
        "liveMa20": TechnicalIndicators.sma([candle["close"] for candle in candles], 20),
    }


def present_market(decision: Optional[dict]) -> Optional[dict]:
    """Phone copy. Trading decisions keep the closed-bar RSI and 15m environment."""
    if not isinstance(decision, dict):
        return decision
    macro = decision.get("macro")
    if isinstance(macro, dict) and isinstance(macro.get("liveRsi"), (int, float)) and isinstance(macro.get("liveMa20"), (int, float)):
        macro["rsi"] = macro["liveRsi"]
        macro["ma20"] = macro["liveMa20"]
    view = decision.get("shortHorizonV2")
    display = view.get("displayEnv") if isinstance(view, dict) else None
    env = view.get("env") if isinstance(view, dict) else None
    if isinstance(display, dict) and isinstance(display.get("states"), dict) and isinstance(env, dict):
        shown = dict(env)
        shown["states"] = display["states"]
        if isinstance(display.get("score"), int):
            shown["score"] = display["score"]
        if isinstance(display.get("label"), str):
            shown["label"] = display["label"]
        view["env"] = shown
    return decision


def diagnose_macro_trend(btc_hourly_candles: Optional[List[dict]], btc_ticker: Optional[dict]) -> dict:
    btc_hourly_candles = get_closed_candles(btc_hourly_candles or [])
    if not btc_hourly_candles or len(btc_hourly_candles) < 15 or not btc_ticker:
        return {
            "trend": "INSUFFICIENT",
            "is_bearish": False,
            "is_strongly_bearish": False,
            "rsi": 50.0,
            "min_required_drop": 5.0,
            "reason": "1H 已收盘K线不足，拒绝发信号"
        }

    closes = [c["close"] for c in btc_hourly_candles]
    curr_price = btc_ticker["price"]
    change24h = btc_ticker["change24h"]

    ma20 = TechnicalIndicators.sma(closes, min(20, len(closes)))
    # Display-only Bollinger bands: 20 closed hourly closes, population variance.
    window = closes[-20:]
    bollinger = None
    if len(window) == 20 and all(math.isfinite(x) and x > 0 for x in window):
        middle = sum(window) / 20
        deviation = math.sqrt(sum((x - middle) ** 2 for x in window) / 20)
        bollinger = {"upper": middle + 2 * deviation, "lower": middle - 2 * deviation}
    ema7 = TechnicalIndicators.ema(closes, 7)
    ema25 = TechnicalIndicators.ema(closes, 25)
    hourly_rsi = TechnicalIndicators.rsi(btc_hourly_candles, 14)

    start_idx12 = max(0, len(closes) - 12)
    drift_12h = ((curr_price - closes[start_idx12]) / closes[start_idx12]) * 100
    start_idx4 = max(0, len(closes) - 4)
    drift_4h = ((curr_price - closes[start_idx4]) / closes[start_idx4]) * 100

    hourly_high = max(c["high"] for c in btc_hourly_candles)
    drop_from_peak = ((hourly_high - curr_price) / hourly_high) * 100 if hourly_high > 0 else 0.0

    is_strictly_bullish = (
        (curr_price > ma20 * 1.002 and ema7 >= ema25 and hourly_rsi >= 52.0 and (drift_12h > 0.4 or drift_4h > 0.5)) or
        (drift_4h > 0.8 and curr_price > ema7)
    )

    is_below_ma20_bearish = curr_price < ma20 * 0.992 and hourly_rsi < 47.0
    is_ema_bearish = ema7 < ema25 and curr_price < ema7 and hourly_rsi < 46.0
    is_drifting_down = drift_12h < -0.45 or drift_4h < -0.55
    is_deep_drop = change24h < -1.8
    is_fallen_from_peak = drop_from_peak > 1.5 and curr_price < ema7 and curr_price < ma20

    is_downtrend = (is_below_ma20_bearish or is_ema_bearish or is_drifting_down or is_deep_drop or is_fallen_from_peak)

    if is_strictly_bullish:
        return {
            "trend": "BULLISH",
            "is_bearish": False,
            "is_strongly_bearish": False,
            "rsi": hourly_rsi,
            "ma20": ma20,
            "bollinger": bollinger,
            "min_required_drop": 0.0,
            "reason": "1H 均线多头向上发散，站稳 MA20 与 EMA7"
        }
    elif is_downtrend:
        is_strong_bear = (hourly_rsi < 40 or drift_12h < -0.8 or change24h < -2.5 or (ema7 < ema25 and curr_price < ma20 * 0.988))
        return {
            "trend": "BEARISH",
            "is_bearish": True,
            "is_strongly_bearish": is_strong_bear,
            "rsi": hourly_rsi,
            "ma20": ma20,
            "bollinger": bollinger,
            "min_required_drop": 5.0,
            "reason": f"1H 处于空头下行通道 (承压 MA20 ${ma20:.1f}, 1H RSI={hourly_rsi:.1f})"
        }
    else:
        return {
            "trend": "RANGING",
            "is_bearish": False,
            "is_strongly_bearish": False,
            "rsi": hourly_rsi,
            "ma20": ma20,
            "bollinger": bollinger,
            "min_required_drop": 0.0,
            "reason": "1H 处于区间震荡平衡态 (均线缠绕，适配动态3级波动模型)"
        }



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

