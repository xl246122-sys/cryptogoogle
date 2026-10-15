#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys
import paramiko

sys.stdout.reconfigure(encoding='utf-8')

REMOTE_CODE = '''#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Crypto-G - Ultra-Short-Term Quantitative Radar Daemon
Running 24/7 on Ubuntu Server (43.163.203.127 - Tokyo Node)
Exclusive BUY Signals Only with Dual-Coin Linkage & Intelligent 3-Tier Volatility Adaptive Range Model
"""

import os
import sys
import time
import math
import json
import logging
import datetime
from typing import Dict, List, Optional, Tuple

# Setup logging
LOG_DIR = "/opt/shotcrypto/logs"
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, "scanner.log")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_FILE, encoding='utf-8')
    ]
)
logger = logging.getLogger("Crypto-G")

# API Configuration
BINANCE_API_BASES = [
    "https://data-api.binance.vision/api/v3",
    "https://api.binance.com/api/v3",
    "https://api1.binance.com/api/v3",
    "https://api2.binance.com/api/v3",
]

# Symbols
MACRO_BENCHMARK = "BTCUSDT"
TARGET_SYMBOLS = ["BTCUSDT"]

# Scanner Settings
SCAN_INTERVAL_SECONDS = 2.0  # High-frequency 2-second scan
MIN_BEARISH_DROP_REQUIRED = 5.0  # Strict 5.0% dip requirement when macro/asset is bearish!
COOLDOWN_SECONDS = 50  # Minimum cooldown between alerts per symbol
RECENT_ALERT_MEMORY = {}  # {symbol: {"time": float, "price": float}}

# Firebase Admin SDK Setup
FCM_INITIALIZED = False
FCM_KEY_PATH = "/opt/shotcrypto/serviceAccountKey.json"

try:
    import firebase_admin
    from firebase_admin import credentials, messaging

    if os.path.exists(FCM_KEY_PATH):
        cred = credentials.Certificate(FCM_KEY_PATH)
        firebase_admin.initialize_app(cred)
        FCM_INITIALIZED = True
        logger.info(">>> Firebase Admin SDK Initialized! Topic broadcast active.")
    else:
        logger.warning("FCM Key not found at %s. Running in log alert mode.", FCM_KEY_PATH)
except Exception as e:
    logger.error("Failed to initialize Firebase Admin SDK: %s", e)


def send_fcm_alert(title: str, body: str, data: Optional[dict] = None) -> bool:
    if not FCM_INITIALIZED:
        logger.info("[ALERT SIMULATED] %s\\n%s", title, body)
        return False
    try:
        payload_data = {k: str(v) for k, v in (data or {}).items()}
        msg = messaging.Message(
            notification=messaging.Notification(title=title, body=body),
            topic="shot_crypto_signals",
            data=payload_data,
            android=messaging.AndroidConfig(
                priority="high",
                notification=messaging.AndroidNotification(
                    channel_id="shot_crypto_signals_v2",
                    sound="default",
                    default_vibrate_timings=True,
                )
            )
        )
        res = messaging.send(msg)
        logger.info(">>> FCM PUSH BROADCAST SUCCESS! MsgID: %s | Title: %s", res, title)
        return True
    except Exception as e:
        logger.error("FCM broadcast failed: %s", e)
        return False


# Binance Direct Market Data Fetchers
import requests
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "CryptoG-QuantEngine/1.02"})


def fetch_ticker(symbol: str) -> Optional[dict]:
    for base in BINANCE_API_BASES:
        try:
            url = f"{base}/ticker/24hr?symbol={symbol}"
            res = SESSION.get(url, timeout=2.5)
            if res.status_code == 200:
                d = res.json()
                return {
                    "symbol": symbol,
                    "price": float(d["lastPrice"]),
                    "change24h": float(d["priceChangePercent"]),
                    "high24h": float(d["highPrice"]),
                    "low24h": float(d["lowPrice"]),
                    "volume24h": float(d["volume"]),
                }
        except Exception:
            continue
    return None


def fetch_klines(symbol: str, interval: str = "1m", limit: int = 35) -> Optional[List[dict]]:
    for base in BINANCE_API_BASES:
        try:
            url = f"{base}/klines?symbol={symbol}&interval={interval}&limit={limit}"
            res = SESSION.get(url, timeout=2.5)
            if res.status_code == 200:
                raw = res.json()
                return [
                    {
                        "time": int(k[0]),
                        "open": float(k[1]),
                        "high": float(k[2]),
                        "low": float(k[3]),
                        "close": float(k[4]),
                        "volume": float(k[5]),
                    }
                    for k in raw
                ]
        except Exception:
            continue
    return None


def fetch_orderbook(symbol: str, limit: int = 20) -> dict:
    for base in BINANCE_API_BASES:
        try:
            url = f"{base}/depth?symbol={symbol}&limit={limit}"
            res = SESSION.get(url, timeout=2.0)
            if res.status_code == 200:
                d = res.json()
                bid_vol = sum(float(b[1]) for b in d.get("bids", []))
                ask_vol = sum(float(a[1]) for a in d.get("asks", []))
                tot = bid_vol + ask_vol
                imb = (bid_vol - ask_vol) / tot if tot > 0 else 0.0
                return {"bid_vol": bid_vol, "ask_vol": ask_vol, "imbalance": imb}
        except Exception:
            continue
    return {"bid_vol": 0.0, "ask_vol": 0.0, "imbalance": 0.0}


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
    def calculate_volatility_regime(candles: List[dict], current_price: float) -> dict:
        """
        Diagnose Volatility Regime (智能识别震荡波动幅度级别):
        - LOW: swing < 0.95% or bandwidth < 1.0% (小幅度波动)
        - MEDIUM: 0.95% <= swing < 2.0% (中度波动)
        - HIGH: swing >= 2.0% (大幅度波动)
        """
        if not candles or len(candles) < 10:
            return {"level": "MEDIUM", "name": "中度波动 (标配箱体)", "tp1": 1.4, "tp2": 3.0, "sl": 0.85, "swing": 1.2}

        window = candles[-min(30, len(candles)):]
        highs = [c["high"] for c in window]
        lows = [c["low"] for c in window]
        closes = [c["close"] for c in window]

        max_h = max(highs)
        min_l = min(lows)
        swing_pct = round(((max_h - min_l) / min_l) * 100, 2) if min_l > 0 else 1.0

        sma20 = sum(closes[-20:]) / min(20, len(closes))
        std20 = math.sqrt(sum((x - sma20) ** 2 for x in closes[-20:]) / min(20, len(closes)))
        bandwidth = round(((std20 * 4) / sma20) * 100, 2) if sma20 > 0 else 1.2

        if swing_pct < 0.95 or bandwidth < 1.0:
            return {"level": "LOW", "name": "小幅度波动 (窄幅小波段)", "tp1": 0.8, "tp2": 1.6, "sl": 0.55, "swing": swing_pct}
        elif swing_pct >= 2.0 or bandwidth >= 2.2:
            return {"level": "HIGH", "name": "大幅度波动 (宽幅拉锯震荡)", "tp1": 2.2, "tp2": 4.5, "sl": 1.2, "swing": swing_pct}
        else:
            return {"level": "MEDIUM", "name": "中度波动 (标准箱体震荡)", "tp1": 1.4, "tp2": 3.0, "sl": 0.85, "swing": swing_pct}

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
            }
        return None


# Macro & Cascade Diagnostics
def diagnose_macro_trend(btc_hourly_candles: Optional[List[dict]], btc_ticker: Optional[dict]) -> dict:
    if not btc_hourly_candles or len(btc_hourly_candles) < 15 or not btc_ticker:
        change24h = btc_ticker["change24h"] if btc_ticker else -0.5
        is_bear = change24h < -1.5
        return {
            "trend": "BEARISH" if is_bear else "RANGING",
            "is_bearish": is_bear,
            "is_strongly_bearish": change24h < -2.5,
            "rsi": 42.0 if is_bear else 50.0,
            "min_required_drop": 5.0 if is_bear else 0.0,
            "reason": "1H K-lines fallback"
        }

    closes = [c["close"] for c in btc_hourly_candles]
    curr_price = btc_ticker["price"]
    change24h = btc_ticker["change24h"]

    ma20 = TechnicalIndicators.sma(closes, min(20, len(closes)))
    ma50 = TechnicalIndicators.sma(closes, min(50, len(closes)))
    ema7 = TechnicalIndicators.ema(closes, 7)
    ema25 = TechnicalIndicators.ema(closes, 25)
    hourly_rsi = TechnicalIndicators.rsi(btc_hourly_candles, 14)

    start_idx12 = max(0, len(closes) - 12)
    drift_12h = ((curr_price - closes[start_idx12]) / closes[start_idx12]) * 100
    start_idx4 = max(0, len(closes) - 4)
    drift_4h = ((curr_price - closes[start_idx4]) / closes[start_idx4]) * 100

    hourly_high = max(c["high"] for c in btc_hourly_candles)
    drop_from_peak = ((hourly_high - curr_price) / hourly_high) * 100 if hourly_high > 0 else 0.0

    # Multi-factor Downtrend Determination:
    is_below_ma20_bearish = curr_price < ma20 * 0.992 and hourly_rsi < 47.0
    is_ema_bearish = ema7 < ema25 and curr_price < ema7 and hourly_rsi < 46.0
    is_drifting_down = drift_12h < -0.45 or drift_4h < -0.55
    is_deep_drop = change24h < -1.8
    is_fallen_from_peak = drop_from_peak > 1.5 and curr_price < ema7 and curr_price < ma20

    is_downtrend = (is_below_ma20_bearish or is_ema_bearish or is_drifting_down or is_deep_drop or is_fallen_from_peak)

    is_strictly_bullish = (curr_price > ma20 * 1.002 and
                           ema7 >= ema25 and
                           hourly_rsi >= 53.0 and
                           drift_12h > 0.4 and
                           change24h > 0.3)

    if is_strictly_bullish:
        return {
            "trend": "BULLISH",
            "is_bearish": False,
            "is_strongly_bearish": False,
            "rsi": hourly_rsi,
            "ma20": ma20,
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
            "min_required_drop": 5.0,  # Strict 5% drop threshold
            "reason": f"1H 处于空头主跌/下行通道 (承压 MA20 ${ma20:.1f}, 1H RSI={hourly_rsi:.1f})"
        }
    else:
        return {
            "trend": "RANGING",
            "is_bearish": False,
            "is_strongly_bearish": False,
            "rsi": hourly_rsi,
            "ma20": ma20,
            "min_required_drop": 0.0,
            "reason": "1H 处于区间震荡平衡态 (均线缠绕，适配智能震荡模型)"
        }


def diagnose_cascade_downtrend(candles: List[dict], ticker: dict) -> Tuple[bool, str]:
    if not candles or len(candles) < 15:
        return False, ""
    closes = [c["close"] for c in candles]
    ema7 = TechnicalIndicators.ema(closes, 7)
    ema25 = TechnicalIndicators.ema(closes, 25)
    curr_price = ticker["price"]

    latest = candles[-1]
    if latest["close"] >= latest["open"] and curr_price >= ema7 * 0.999:
        return False, ""

    is_ema_waterfall = ema7 < ema25 and curr_price < ema7 * 0.9985
    recent5 = candles[-5:]
    lower_highs = sum(1 for i in range(1, len(recent5)) if recent5[i]["high"] <= recent5[i - 1]["high"] * 1.0005)
    is_consecutive_drop = lower_highs >= 3

    start_idx12 = max(0, len(closes) - 12)
    short_drop_pct = ((curr_price - closes[start_idx12]) / closes[start_idx12]) * 100
    is_sharp_drop = short_drop_pct < -0.8

    if (is_ema_waterfall and is_consecutive_drop) or (is_ema_waterfall and ticker["change24h"] < -2.5) or (is_sharp_drop and is_ema_waterfall):
        reason = f"单边空头瀑布下行 (EMA7 {ema7:.4f} < EMA25 {ema25:.4f}, 短线跌幅 {short_drop_pct:.2f}%)"
        return True, reason

    return False, ""


def evaluate_symbol_signals(symbol: str, ticker: dict, micro_candles: List[dict], macro_trend: dict) -> Optional[dict]:
    curr_price = ticker["price"]
    change24h = ticker["change24h"]
    high24h = ticker["high24h"]

    # 1. Cascade Waterfall Check
    is_cascading, cascade_reason = diagnose_cascade_downtrend(micro_candles, ticker)
    if is_cascading:
        logger.debug("[瀑布拦截] %s 处于 %s，全面拦截买入！", symbol, cascade_reason)
        return None

    # Calculate Drop from High
    micro_high = max(c["high"] for c in micro_candles)
    peak_price = max(high24h, micro_high, curr_price)
    drop_from_peak_pct = ((peak_price - curr_price) / peak_price) * 100 if peak_price > 0 else 0.0
    effective_drop_pct = max(drop_from_peak_pct, abs(min(0.0, change24h)))

    # Determine Bearish Trend (Global BTC Macro OR Asset itself is weak)
    is_bearish = macro_trend["is_bearish"] or change24h < -1.8

    # Calculate Technicals on 1m Candles
    sma20, std20, upper_bb, lower_bb, vwap = TechnicalIndicators.vwap_and_bands(micro_candles, 20)
    rsi14 = TechnicalIndicators.rsi(micro_candles, 14)
    atr14 = TechnicalIndicators.atr(micro_candles, 14)
    vwap_atr_spread = (vwap - curr_price) / atr14 if atr14 > 0 else 0.0

    # Volume burst ratio
    vols = [c["volume"] for c in micro_candles]
    avg_vol = sum(vols[-15:-1]) / 14.0 if len(vols) >= 15 else vols[-1]
    vol_surge = vols[-1] / max(0.1, avg_vol)

    closes = [c["close"] for c in micro_candles]
    ema7 = TechnicalIndicators.ema(closes, 7)
    ema25 = TechnicalIndicators.ema(closes, 25)

    recent_lows = [c["low"] for c in micro_candles[-12:]]
    swing_bottom = min(recent_lows)
    bounce_from_bottom_pct = ((curr_price - swing_bottom) / swing_bottom) * 100 if swing_bottom > 0 else 0.0
    latest_candle = micro_candles[-1]
    is_green_reversal = latest_candle["close"] >= latest_candle["open"]

    orderbook = fetch_orderbook(symbol, 20)

    # Strategy 1: Confirmed Bottom Rebound
    is_bottom_rebound = (
        bounce_from_bottom_pct >= 0.20 and
        bounce_from_bottom_pct <= 2.2 and
        is_green_reversal and
        curr_price >= ema7 * 0.9985 and
        30.0 <= rsi14 <= 64.0 and
        orderbook["imbalance"] >= -0.08
    )

    # Strategy 2: Bullish RSI Divergence
    rsi_div = TechnicalIndicators.detect_rsi_divergence(micro_candles)

    # Strategy 3: Flash Crash Rebound
    is_flash_crash = (rsi14 < 24.0 and curr_price <= lower_bb * 1.002 and vwap_atr_spread >= 1.5)

    # Strategy 4: Burst Breakout (放量突破 - 仅限顺势环境)
    is_burst = (not is_bearish and vol_surge >= 2.0 and curr_price >= upper_bb * 0.998 and 58.0 < rsi14 < 78.0)

    # Diagnose Volatility Regime of the micro asset
    vol_regime = TechnicalIndicators.calculate_volatility_regime(micro_candles, curr_price)

    # =========================================================================
    # SCENARIO A: BEARISH TREND -> Strictly enforce 5% drop requirement
    # =========================================================================
    if is_bearish:
        if effective_drop_pct < MIN_BEARISH_DROP_REQUIRED:
            logger.debug("[空头防阴跌拦截] %s 处于空头通道且标的高位跌幅仅 %.2f%% (< 5.0%%)，全面拦截！", symbol, effective_drop_pct)
            return None

        if is_bottom_rebound:
            tp1 = round(curr_price * 1.018, 4)
            tp2 = round(curr_price * 1.038, 4)
            sl = round(curr_price * 0.989, 4)
            title = f"🎯 [空头5%跌幅抄底 · 触底企稳买入] {symbol}"
            body = (
                f"买入价: ${curr_price:.4f} | 高位累计跌幅: {effective_drop_pct:.2f}% (≥5%已确认)\n"
                f"止盈TP1: ${tp1:.4f} (+1.8%) | 止盈TP2: ${tp2:.4f} (+3.8%)\n"
                f"防守止损SL: ${sl:.4f} (-1.1%) | 预计持仓: 20m - 2h\n"
                f"模型建议: 满足空头 5% 跌幅门槛，低点 ${swing_bottom:.4f} 探底企稳，右侧放量突破 EMA7，果断买入！"
            )
            return {"symbol": symbol, "type": "BUY", "strategy": "BOTTOM_REBOUND", "price": curr_price, "tp1": tp1, "tp2": tp2, "sl": sl, "title": title, "body": body}

        elif rsi_div:
            tp1 = round(curr_price * 1.018, 4)
            tp2 = round(curr_price * 1.036, 4)
            sl = round(curr_price * 0.990, 4)
            title = f"🎯 [空头5%跌幅抄底 · RSI底背离预警] {symbol}"
            body = (
                f"买入价: ${curr_price:.4f} | 高位累计跌幅: {effective_drop_pct:.2f}% (≥5%已确认)\n"
                f"止盈TP1: ${tp1:.4f} (+1.8%) | 止盈TP2: ${tp2:.4f} (+3.6%)\n"
                f"防守止损SL: ${sl:.4f} (-1.0%) | 预计持仓: 15m - 1.5h\n"
                f"模型建议: 价格创低但 RSI 强势抬升形成看涨底背离，右侧收阳突破，深度超跌确认买入！"
            )
            return {"symbol": symbol, "type": "BUY", "strategy": "RSI_DIVERGENCE", "price": curr_price, "tp1": tp1, "tp2": tp2, "sl": sl, "title": title, "body": body}

        elif is_flash_crash:
            tp1 = round(curr_price * 1.015, 4)
            tp2 = round(curr_price * 1.032, 4)
            sl = round(curr_price * 0.991, 4)
            title = f"⚡ [暴跌抄底买入预警 · VWAP价差过滤通过] {symbol}"
            body = (
                f"买入价: ${curr_price:.4f} | RSI={rsi14:.1f} | VWAP偏离={vwap_atr_spread:.2f} ATR\n"
                f"止盈TP1: ${tp1:.4f} (+1.5%) | 止盈TP2: ${tp2:.4f} (+3.2%)\n"
                f"防守止损SL: ${sl:.4f} (-0.9%) | 预计持仓: 15m - 1h\n"
                f"模型建议: 满足 5% 跌幅门槛，VWAP 价差过滤器放行 (>=1.5 ATR)，高胜率 Snap-Back 反弹抄底买入！"
            )
            return {"symbol": symbol, "type": "BUY", "strategy": "FLASH_CRASH_REBOUND", "price": curr_price, "tp1": tp1, "tp2": tp2, "sl": sl, "title": title, "body": body}

    # =========================================================================
    # SCENARIO B: RANGING OR BULLISH -> Auto-Adaptive 3-Tier Volatility Oscillation
    # =========================================================================
    else:
        # 1. Burst Breakout
        if is_burst:
            tp1 = round(curr_price * 1.022, 4)
            tp2 = round(curr_price * 1.045, 4)
            sl = round(curr_price * 0.988, 4)
            title = f"🚀 [爆发买入预警] {symbol} 蓄力突围"
            body = (
                f"建议买入价: ${curr_price:.4f} | 放量 {vol_surge:.1f}x 冲破上轨\n"
                f"止盈TP1: ${tp1:.4f} (+2.2%) | 止盈TP2: ${tp2:.4f} (+4.5%)\n"
                f"防守止损SL: ${sl:.4f} (-1.2%) | 预计持仓: 15m - 1.5h\n"
                f"模型建议: 大盘多头环境，动能充沛，顺应大势做多买入！"
            )
            return {"symbol": symbol, "type": "BUY", "strategy": "BURST", "price": curr_price, "tp1": tp1, "tp2": tp2, "sl": sl, "title": title, "body": body}

        # 2. Confirmed Bottom Rebound at Support
        if is_bottom_rebound:
            tp1 = round(curr_price * (1.0 + vol_regime["tp1"] / 100.0), 4)
            tp2 = round(curr_price * (1.0 + vol_regime["tp2"] / 100.0), 4)
            sl = round(curr_price * (1.0 - vol_regime["sl"] / 100.0), 4)
            title = f"🎯 [箱体探底企稳 · {vol_regime['name']}买入] {symbol}"
            body = (
                f"建议买入价: ${curr_price:.4f} | 探底低点: ${swing_bottom:.4f}\n"
                f"止盈TP1: ${tp1:.4f} (+{vol_regime['tp1']}%) | 止盈TP2: ${tp2:.4f} (+{vol_regime['tp2']}%) | 止损SL: -{vol_regime['sl']}%\n"
                f"预计持仓: 15m - 1.5h | 智能适配: {vol_regime['name']} (振幅 {vol_regime['swing']}%)\n"
                f"模型建议: 价格在箱体底部探底成功，右侧收阳突破 EMA7，买方托底坚决，建议果断买入！"
            )
            return {"symbol": symbol, "type": "BUY", "strategy": "BOTTOM_REBOUND", "price": curr_price, "tp1": tp1, "tp2": tp2, "sl": sl, "title": title, "body": body}

        # 3. 3-Tier Volatility-Adaptive Range Oscillation Models
        # TIER 1: 小幅度波动 (Narrow / Micro Range Buy)
        if vol_regime["level"] == "LOW":
            local_min = min(float(c["low"]) for c in micro_candles[-12:])
            is_micro_support = (curr_price <= local_min * 1.0025 or curr_price <= lower_bb * 1.004 or curr_price <= sma20 * 0.9985)
            if is_micro_support and rsi14 <= 46.0 and (is_green_reversal or curr_price >= local_min * 1.001):
                tp1 = round(curr_price * (1.0 + vol_regime["tp1"] / 100.0), 4)
                tp2 = round(curr_price * (1.0 + vol_regime["tp2"] / 100.0), 4)
                sl = round(curr_price * (1.0 - vol_regime["sl"] / 100.0), 4)
                title = f"⚡ [区间震荡 · 小波段低吸预警] {symbol}"
                body = (
                    f"建议买入价: ${curr_price:.4f} | 智能适配: {vol_regime['name']} (振幅仅 {vol_regime['swing']}%)\n"
                    f"止盈TP1: ${tp1:.4f} (+{vol_regime['tp1']}%) | 止盈TP2: ${tp2:.4f} (+{vol_regime['tp2']}%) | 止损SL: -{vol_regime['sl']}%\n"
                    f"预计持仓: 10m - 40m\n"
                    f"模型建议: 微波段回踩下轨支撑，RSI低位蓄能 ({rsi14:.1f})，小波段快进快出！"
                )
                return {"symbol": symbol, "type": "BUY", "strategy": "RANGE_MICRO", "price": curr_price, "tp1": tp1, "tp2": tp2, "sl": sl, "title": title, "body": body}

        # TIER 2: 中度波动 (Medium Box Buy - 标配箱体)
        elif vol_regime["level"] == "MEDIUM":
            is_box_support = (curr_price <= lower_bb * 1.008 or curr_price <= swing_bottom * 1.004 or curr_price <= sma20 * 0.996)
            if is_box_support and rsi14 <= 43.0 and is_green_reversal:
                tp1 = round(curr_price * (1.0 + vol_regime["tp1"] / 100.0), 4)
                tp2 = round(curr_price * (1.0 + vol_regime["tp2"] / 100.0), 4)
                sl = round(curr_price * (1.0 - vol_regime["sl"] / 100.0), 4)
                title = f"🎯 [区间震荡 · 中波段箱体低吸预警] {symbol}"
                body = (
                    f"建议买入价: ${curr_price:.4f} | 智能适配: {vol_regime['name']} (振幅 {vol_regime['swing']}%)\n"
                    f"止盈TP1: ${tp1:.4f} (+{vol_regime['tp1']}%) | 止盈TP2: ${tp2:.4f} (+{vol_regime['tp2']}%) | 止损SL: -{vol_regime['sl']}%\n"
                    f"预计持仓: 20m - 1.5h\n"
                    f"模型建议: 箱体下轨支撑区探底企稳，右侧收阳站稳，高胜率捕捉箱体反抽！"
                )
                return {"symbol": symbol, "type": "BUY", "strategy": "RANGE_MEDIUM", "price": curr_price, "tp1": tp1, "tp2": tp2, "sl": sl, "title": title, "body": body}

        # TIER 3: 大幅度波动 (Wide Range Buy - 宽幅拉锯)
        elif vol_regime["level"] == "HIGH":
            is_wide_support = (curr_price <= lower_bb * 1.005 or (vwap_atr_spread >= 1.0 and curr_price <= sma20 * 0.992))
            if is_wide_support and rsi14 <= 36.0 and is_green_reversal:
                tp1 = round(curr_price * (1.0 + vol_regime["tp1"] / 100.0), 4)
                tp2 = round(curr_price * (1.0 + vol_regime["tp2"] / 100.0), 4)
                sl = round(curr_price * (1.0 - vol_regime["sl"] / 100.0), 4)
                title = f"⚡ [区间震荡 · 宽幅拉锯低吸预警] {symbol}"
                body = (
                    f"建议买入价: ${curr_price:.4f} | 智能适配: {vol_regime['name']} (振幅 {vol_regime['swing']}%)\n"
                    f"止盈TP1: ${tp1:.4f} (+{vol_regime['tp1']}%) | 止盈TP2: ${tp2:.4f} (+{vol_regime['tp2']}%) | 止损SL: -{vol_regime['sl']}%\n"
                    f"预计持仓: 30m - 2.5h\n"
                    f"模型建议: 宽幅下轨极度超卖 ({rsi14:.1f})，高弹性均值回归抄底做多！"
                )
                return {"symbol": symbol, "type": "BUY", "strategy": "RANGE_WIDE", "price": curr_price, "tp1": tp1, "tp2": tp2, "sl": sl, "title": title, "body": body}

    return None


def run_scanner_loop():
    logger.info("=================================================================")
    logger.info("  Crypto-G 24/7 Quantum Scanner Engine Starting...")
    logger.info("  Host Server : 43.163.203.127 (Tencent Cloud Japan Tokyo Node)")
    logger.info("  Target Pairs: %s", ", ".join(TARGET_SYMBOLS))
    logger.info("  Macro Anchor: %s (1-Hour Klines & Multi-factor Drift)", MACRO_BENCHMARK)
    logger.info("  Core Guard  : Bearish 5.0%% Drop Hard Threshold (防阴跌接飞刀)")
    logger.info("  Adaptive Box: 3-Tier Volatility (小波动/中度波动/大幅度波动自动适配)")
    logger.info("  Push Topic  : shot_crypto_signals (Firebase Cloud Messaging)")
    logger.info("=================================================================")

    scan_count = 0
    while True:
        try:
            start_time = time.time()
            scan_count += 1

            # 1. Fetch BTC Macro Trend
            btc_ticker = fetch_ticker(MACRO_BENCHMARK)
            btc_1h_klines = fetch_klines(MACRO_BENCHMARK, interval="1h", limit=50)
            macro_trend = diagnose_macro_trend(btc_1h_klines, btc_ticker)

            if scan_count % 30 == 1:
                btc_p = btc_ticker["price"] if btc_ticker else 0.0
                logger.info(
                    "[HEARTBEAT] BTC: $%.1f | 大盘风向: %s | 1H RSI: %.1f | 判定: %s",
                    btc_p,
                    macro_trend["trend"],
                    macro_trend["rsi"],
                    macro_trend["reason"]
                )

            # 2. Iterate each target symbol
            for symbol in TARGET_SYMBOLS:
                ticker = fetch_ticker(symbol)
                if not ticker:
                    continue

                micro_candles = fetch_klines(symbol, interval="1m", limit=35)
                if not micro_candles or len(micro_candles) < 20:
                    continue

                curr_p = ticker["price"]
                now = time.time()

                # Anti-spam cooldown
                if symbol in RECENT_ALERT_MEMORY:
                    last_alert = RECENT_ALERT_MEMORY[symbol]
                    elapsed = now - last_alert["time"]
                    if elapsed < COOLDOWN_SECONDS:
                        continue
                    if elapsed < 150 and curr_p <= last_alert["price"] * 1.002:
                        continue

                # Run Quant Model Evaluation
                signal = evaluate_symbol_signals(symbol, ticker, micro_candles, macro_trend)
                if signal:
                    # Broadcast to Android phone via Firebase
                    logger.info(">>> DETECTED SIGNAL: %s Strategy=%s Price=%s", symbol, signal["strategy"], signal["price"])
                    send_fcm_alert(
                        title=signal["title"],
                        body=signal["body"],
                        data={
                            "symbol": signal["symbol"],
                            "type": signal["type"],
                            "strategy": signal["strategy"],
                            "price": str(signal["price"]),
                            "tp1": str(signal["tp1"]),
                            "tp2": str(signal["tp2"]),
                            "sl": str(signal["sl"]),
                        }
                    )
                    RECENT_ALERT_MEMORY[symbol] = {"time": now, "price": curr_p}
                    time.sleep(2.0)

            # Control frequency
            elapsed = time.time() - start_time
            sleep_time = max(0.5, SCAN_INTERVAL_SECONDS - elapsed)
            time.sleep(sleep_time)

        except KeyboardInterrupt:
            logger.info("Scanner stopped by user.")
            break
        except Exception as e:
            logger.error("Error in scan loop: %s", e)
            time.sleep(2.0)


if __name__ == "__main__":
    run_scanner_loop()
'''

raise SystemExit(
    "This old uploader is disabled. It used to overwrite the live daemon and restart the service. "
    "The current source is scratch/remote_scanner_daemon.py."
)
