import math
from typing import Dict, List, Optional, Tuple
from .clock import clock as time
from .config import *


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

