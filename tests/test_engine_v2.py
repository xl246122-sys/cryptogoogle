"""Acceptance replay for short-horizon-v2 and the plan gates."""
import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptog.engine_v2 import build_context, detect_s1, detect_s2, environment, plan_issue, scan, widen_stop

CST = timezone(timedelta(hours=8))
FIXTURE = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "btc_v2_20261008_17.json"
START = int(datetime(2026, 10, 11, tzinfo=CST).timestamp() * 1000)


def load():
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    cols = raw["columns"]
    return {k: [dict(zip(cols, row)) for row in raw[k]] for k in ("1d", "4h", "1h", "15m", "5m", "1m")}


def replay(data):
    def closed(key, now, n):
        return [bar for bar in data[key] if bar["close_time"] < now][-n:]

    seen, signals = set(), []
    ctx = m15 = m5 = None
    slot = None
    for bar in data["1m"]:
        now = bar["time"] + 1000
        if now < START:
            continue
        if now // 900_000 != slot:
            slot = now // 900_000
            ctx = build_context(closed("1d", now, 300), closed("4h", now, 300), closed("1h", now, 300), closed("15m", now, 300), now)
            m15 = closed("15m", now, 256)
            m5 = closed("5m", now, 256)
        if m5 and now - m5[-1]["close_time"] > 300_000:
            m5 = closed("5m", now, 256)
        signal, _, _ = scan(m15, m5, closed("1m", now, 40), bar["open"], {"spread": 0.001, "imbalance": 0}, ctx, now)
        if signal and signal["structure_key"] not in seen:
            seen.add(signal["structure_key"])
            signals.append(signal)
    return signals


class EngineV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = load()
        cls.signals = replay(cls.data)

    def test_week_emits_at_least_six_watch_signals_inside_the_cost_gate(self):
        self.assertGreaterEqual(len(self.signals), 6)
        for signal in self.signals:
            gross = (signal["target_tp1"] / signal["entry_price"] - 1) * 100
            self.assertGreaterEqual(gross, 0.74 - 1e-9, signal["structure_key"])
            self.assertGreaterEqual(signal["net_tp1"], 0.50 - 1e-9)
            self.assertGreaterEqual(signal["stop_loss_pct"], 0.35 - 1e-9)
            self.assertLessEqual(signal["stop_loss_pct"], 1.20 + 1e-9)
            self.assertEqual(signal["tier_label"], "观察级·未验证")
            self.assertEqual(signal["friction_pct"], 0.24)
            self.assertEqual(signal["rule_version"], "short-horizon-v2")
            self.assertNotEqual(signal["module"], "S5")

    def test_79800_flush_is_rejected_because_the_4h_is_bearish(self):
        data = self.data
        flush = next(bar for bar in data["15m"] if bar["low"] == 79800)
        trigger = next(bar for bar in data["15m"] if bar["time"] > flush["time"] and bar["close"] > bar["open"])
        now = trigger["close_time"] + 2000

        def closed(key, n):
            return [bar for bar in data[key] if bar["close_time"] < now][-n:]

        ctx = build_context(closed("1d", 300), closed("4h", 300), closed("1h", 300), closed("15m", 300), now)
        env = environment(ctx, trigger["close"], now)
        self.assertEqual(env["states"]["h4"], "DOWN")
        self.assertFalse(env["gates"]["S3"])
        self.assertFalse(env["gates"]["S4"])
        self.assertTrue(env["gates"]["S1"])
        setup = detect_s1(closed("15m", 80), ctx, env)
        self.assertIn("4H 空头要求 ≥3.5%", setup["blocked"])
        self.assertFalse(any(signal["module"] == "S1" and flush["time"] <= signal["confirmation_time"] <= trigger["close_time"] + 30 * 60_000
                             for signal in self.signals))

    def test_oct17_boll_retest_fails_the_one_to_one_gate(self):
        data = self.data
        moment = int(datetime(2026, 10, 17, 2, 45, tzinfo=CST).timestamp() * 1000)
        bar = next(item for item in data["15m"] if item["time"] == moment)
        now = bar["close_time"] + 2000

        def closed(key, n):
            return [item for item in data[key] if item["close_time"] < now][-n:]

        ctx = build_context(closed("1d", 300), closed("4h", 300), closed("1h", 300), closed("15m", 300), now)
        env = environment(ctx, bar["close"], now)
        self.assertTrue(env["gates"]["S2"])
        setup = widen_stop(detect_s2(closed("15m", 80), ctx, env))
        self.assertIn("净盈亏比", plan_issue(setup))
        stamped = [signal["timestamp"] for signal in self.signals]
        self.assertFalse(any(datetime.fromtimestamp(ms / 1000, CST).day == 17 for ms in stamped))

    def test_s2_closed_text_names_the_line_that_broke(self):
        def frame(close, ema99, ema25):
            return {"close": close, "ema99": ema99, "ema25": ema25}

        ctx = {"d1": frame(100, 90, 95), "h4": frame(88, 80, 85), "h1": frame(88, 80, 85)}
        four_hour = environment(ctx, 88, 1_700_000_000_000)
        self.assertFalse(four_hour["gates"]["S2"])
        self.assertTrue(any("4H 收盘跌破日线 EMA99" in line for line in four_hour["closed"]))
        self.assertFalse(any("日线已跌破" in line for line in four_hour["closed"]))
        ctx["d1"] = frame(80, 90, 95)
        daily = environment(ctx, 80, 1_700_000_000_000)
        self.assertTrue(any("日线已跌破 EMA99" in line for line in daily["closed"]))


if __name__ == "__main__":
    unittest.main()
