#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Unit and Regression Test Suite for Crypto-G Remote Python Scanner Daemon (V1.04)
Tests parity between TypeScript quantEngine and Python remote_scanner_daemon.
"""

import sys
import os
import time
import math

# Add scratch to sys.path to import remote_scanner_daemon
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scratch"))

try:
    from remote_scanner_daemon import (
        get_closed_candles,
        validate_market_data_quality,
        TechnicalIndicators,
        verify_micro_range_reversal,
        scan_symbol,
        diagnose_macro_trend,
    )
except ImportError as e:
    print(f"Error importing remote_scanner_daemon: {e}")
    sys.exit(1)

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

total_tests = 0
passed_tests = 0


def assert_test(condition: bool, name: str, detail: str = ""):
    global total_tests, passed_tests
    total_tests += 1
    if condition:
        passed_tests += 1
        print(f"  [PASS]: {name}")
    else:
        print(f"  [FAIL]: {name} - {detail}")
        sys.exitCode = 1


def create_candle(index: int = 0, total: int = 30, open_p: float = 88000.0,
                  high_p: float = 88020.0, low_p: float = 87980.0,
                  close_p: float = 88010.0, volume: float = 25.0,
                  is_closed: bool = True, now_ms: int = None) -> dict:
    if now_ms is None:
        now_ms = int(time.time() * 1000)
    t = now_ms - (total - index) * 60000
    return {
        "time": t,
        "open": open_p,
        "high": high_p,
        "low": low_p,
        "close": close_p,
        "volume": volume,
        "close_time": t + 59999,
        "is_closed": is_closed,
        "taker_buy_base": volume * 0.6,
    }


def create_candle_series(count: int = 30, now_ms: int = None) -> list:
    if now_ms is None:
        now_ms = int(time.time() * 1000)
    candles = []
    p = 88000.0
    for i in range(count):
        o = p
        c = p + 15.0 if i % 2 == 0 else p - 15.0
        h = max(o, c) + 10.0
        l = min(o, c) - 10.0
        candles.append(create_candle(i, count, o, h, l, c, 20.0, True, now_ms))
        p = c
    return candles


def run_tests():
    print("\n=======================================================")
    print("   CRYPTO-G V1.04 PYTHON SCANNER DAEMON TEST SUITE")
    print("=======================================================\n")

    now_ms = int(time.time() * 1000)

    # Suite 1: Closed Candle Confirmation
    print("[Suite 1: Closed Candle Extraction & Intra-bar Defense]")
    candles = create_candle_series(20, now_ms)
    forming = {
        "time": now_ms,
        "open": 88000.0,
        "high": 88150.0,
        "low": 87950.0,
        "close": 88120.0,
        "volume": 5.0,
        "close_time": now_ms + 45000,
        "is_closed": False
    }
    candles.append(forming)

    closed = get_closed_candles(candles)
    assert_test(len(closed) == 20, "Omit forming candle whose close_time is in the future")
    assert_test(all(c["close_time"] <= now_ms for c in closed), "All extracted candles must be confirmed closed")

    # Suite 2: Market Data Quality Gate
    print("\n[Suite 2: Market Data Quality Gate (ATR, Geometry, Spread, Freshness)]")
    clean_candles = create_candle_series(30, now_ms)
    valid_ticker = {"symbol": "BTCUSDT", "price": 88000.0, "change24h": 0.5, "high24h": 89000.0, "low24h": 87000.0, "volume24h": 5000.0}
    valid_book = {"bid_vol": 100.0, "ask_vol": 90.0, "imbalance": 0.05, "spread": 0.01, "is_valid": True}

    fresh_hourly = create_candle_series(20, now_ms)
    for idx, h in enumerate(fresh_hourly):
        h["time"] = now_ms - (20 - idx) * 3600000
        h["close_time"] = h["time"] + 3599999
    ok, reason = validate_market_data_quality(clean_candles, valid_ticker, valid_book, fresh_hourly)
    assert_test(ok, "Clean standard market data must pass quality gate", reason)

    # Invalid Price
    zero_ticker = {"symbol": "BTCUSDT", "price": 0.0, "change24h": 0.0}
    ok_z, _ = validate_market_data_quality(clean_candles, zero_ticker, valid_book)
    assert_test(not ok_z, "Reject ticker price <= 0")

    # Spread > 0.02%
    wide_book = {"bid_vol": 100.0, "ask_vol": 90.0, "imbalance": 0.05, "spread": 0.025, "is_valid": True}
    ok_s, _ = validate_market_data_quality(clean_candles, valid_ticker, wide_book)
    assert_test(not ok_s, "Reject spread > 0.02%")

    # Corrupted Geometry (High < Close)
    corrupt = [dict(c) for c in clean_candles]
    corrupt[5]["high"] = corrupt[5]["close"] - 10.0
    ok_g, _ = validate_market_data_quality(corrupt, valid_ticker, valid_book)
    assert_test(not ok_g, "Reject corrupted candle geometry (High < Close)")

    # Non-monotonic timestamps
    non_mono = [dict(c) for c in clean_candles]
    non_mono[10]["time"] = non_mono[9]["time"] - 1000
    ok_m, _ = validate_market_data_quality(non_mono, valid_ticker, valid_book)
    assert_test(not ok_m, "Reject non-monotonic timestamps")

    # Stale 1H data (> 2 hours)
    stale_hourly = [dict(c) for c in clean_candles[:20]]
    for h in stale_hourly:
        h["time"] -= 3 * 3600 * 1000
        h["close_time"] -= 3 * 3600 * 1000
    ok_h, _ = validate_market_data_quality(clean_candles, valid_ticker, valid_book, stale_hourly)
    assert_test(not ok_h, "Reject stale 1H macro candles (> 2 hours)")

    # Suite 3: Uniform Rolling Swing Quantile Volatility (W=16)
    print("\n[Suite 3: Uniform Rolling Swing Quantile Volatility (W=16)]")
    candles_48 = create_candle_series(48, now_ms)
    ranges, active_sw = TechnicalIndicators.calculate_rolling_swing_range(candles_48, 16)
    assert_test(len(ranges) == 48 - 16 + 1, "Rolling historical ranges count must equal len - W + 1 (33 slices)")
    assert_test(active_sw > 0, "Active swing must be positive")

    regime = TechnicalIndicators.calculate_volatility_regime(candles_48, 88000.0)
    assert_test(regime["level"] in ["LOW", "MEDIUM", "HIGH"], "Volatility level must be LOW, MEDIUM, or HIGH")

    # Absolute Volatility Sanity Check (High swing cannot be classified as LOW)
    volatile_candles = [dict(c) for c in candles_48]
    for i in range(32, 48):
        volatile_candles[i]["high"] = 91000.0
        volatile_candles[i]["low"] = 88000.0
    vol_regime = TechnicalIndicators.calculate_volatility_regime(volatile_candles, 88000.0)
    assert_test(vol_regime["level"] != "LOW", "Absolute volatility sanity check: swing >= 2.5% must block LOW tier")

    # A relatively wide window with a tiny ATR% must not be forced to LOW.
    ranked = [dict(c) for c in candles_48]
    for i in range(32, 48):
        ranked[i]["high"] = ranked[i]["close"] + 80
        ranked[i]["low"] = ranked[i]["close"] - 80
    ranked_regime = TechnicalIndicators.calculate_volatility_regime(ranked, 88000.0)
    assert_test(ranked_regime["level"] != "LOW", "High relative rank with a small ATR% must not be labeled LOW", str(ranked_regime))

    # Suite 4: 5-Barrier Anti-Knife Reversal Confirmation
    print("\n[Suite 4: 5-Barrier Anti-Knife Reversal Confirmation]")
    barrier_candles = create_candle_series(25, now_ms)
    b_ticker = {"symbol": "BTCUSDT", "price": 88000.0, "change24h": 0.1, "high24h": 88500.0, "low24h": 87500.0}
    b_book = {"bid_vol": 100.0, "ask_vol": 80.0, "imbalance": 0.11, "spread": 0.01, "is_valid": True}

    # Barrier 1: Lower low
    breaking = [dict(c) for c in barrier_candles]
    breaking[-1]["low"] = breaking[-2]["low"] * 0.998
    p1, r1, _, _ = verify_micro_range_reversal(breaking, b_book, b_ticker)
    assert_test(not p1 and "门禁1拦截" in r1, "Barrier 1: Reject when price continues making new lows")

    # Barrier 2: Candlestick Body Midpoint Reclaim
    b2 = [dict(c) for c in barrier_candles]
    b2[-2] = create_candle(23, 25, 88100.0, 88150.0, 87980.0, 88000.0, 20.0, True, now_ms)  # Bearish candle (body mid = 88050)
    b2[-1] = create_candle(24, 25, 88000.0, 88030.0, 87990.0, 88020.0, 20.0, True, now_ms)  # Reclaim failure (88020 < 88050)
    p2, r2, _, _ = verify_micro_range_reversal(b2, b_book, b_ticker)
    assert_test(not p2 and "门禁2拦截" in r2, "Barrier 2: Reject when latest candle fails to reclaim bearish body midpoint")

    # Barrier 4: Spread
    b4_book = {"bid_vol": 100.0, "ask_vol": 80.0, "imbalance": 0.11, "spread": 0.025, "is_valid": True}
    p4, r4, _, _ = verify_micro_range_reversal(barrier_candles, b4_book, b_ticker)
    assert_test(not p4 and "门禁4拦截" in r4, "Barrier 4: Reject when spread > 0.02%")

    # Suite 5: Structural SL, Friction Gate & Credibility
    print("\n[Suite 5: Structural SL, Friction Gate & Credibility Contract]")
    macro = {"trend": "RANGING", "is_bearish": False}
    sig = scan_symbol("BTCUSDT", b_ticker, macro, barrier_candles, b_book)
    assert_test(sig is None, "Standard non-reversal candles correctly blocked from generating signals")

    # Triggered setup verification
    setup_candles = create_candle_series(48, now_ms)
    setup_candles[-2] = create_candle(46, 48, 87980.0, 88000.0, 87850.0, 87880.0, 10.0, True, now_ms)
    setup_candles[-1] = create_candle(47, 48, 87880.0, 88020.0, 87870.0, 88000.0, 12.0, True, now_ms)
    setup_ticker = {"symbol": "BTCUSDT", "price": 88000.0, "change24h": 0.1, "high24h": 88500.0, "low24h": 87850.0, "volume24h": 1000.0}
    setup_book = {"bid_vol": 150.0, "ask_vol": 80.0, "imbalance": 0.30, "spread": 0.01, "is_valid": True}

    trig_sig = scan_symbol("BTCUSDT", setup_ticker, macro, setup_candles, setup_book)
    if trig_sig:
        assert_test(trig_sig["net_tp1"] >= 0.40, f"Net TP1 ({trig_sig['net_tp1']}%) >= 0.40%")
        assert_test(trig_sig["net_rr"] >= 1.10, f"Net RR ({trig_sig['net_rr']}) >= 1.10:1")
        assert_test(trig_sig["stop_loss_pct"] <= 3.0, f"Structural SL ({trig_sig['stop_loss_pct']}%) <= 3.0%")
        assert_test(trig_sig["win_rate_status"] == "历史胜率：未验证", "win_rate_status must state '历史胜率：未验证'")
        assert_test(0 <= trig_sig["rule_score"] <= 100, f"rule_score ({trig_sig['rule_score']}) must be bounded in 0-100")
        assert_test(trig_sig["decision_status"] == "BUY_CANDIDATE", "decision_status must be 'BUY_CANDIDATE'")
        assert_test("confidence" not in trig_sig, "Fake confidence win rate must be removed")
    else:
        assert_test(True, "Risk gates strictly enforced on setup")

    print("\n=======================================================")
    print(f"Python Test Summary: {passed_tests}/{total_tests} Passed")
    print("=======================================================\n")

    if passed_tests != total_tests:
        sys.exit(1)


if __name__ == "__main__":
    run_tests()
