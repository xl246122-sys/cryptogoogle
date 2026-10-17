import os
import tempfile
import unittest

from cryptog.config import V2_L1_MIN_SAMPLES, V2_S1_MIN_DROP_PCT, V2_SHADOW_MS, V2_TRIAL_MS
from cryptog.evolution import (
    Pipeline, accept_adjustment, apply_release, drawdown_r, fit_meta_label, push_policy,
)
from cryptog.ledger import Ledger

T0 = 1_700_000_000_000
GOOD = {"trades": 80, "expectancyPct": 0.20, "bootstrapLower95": 0.05, "winRate": 0.56,
        "profitFactor": 1.40, "perDay": 1.2, "dsr": 0.99}
DAY = 86_400_000


def signal(module="S1"):
    return {
        "module": module, "rule_version": "short-horizon-v2", "tier": "WATCH", "tier_label": "观察级·未验证",
        "strategy_name_zh": "【观察级·未验证】BTC 急跌收回",
        "v2": {"tier": "WATCH", "tierLabel": "观察级·未验证"},
    }


class EvolutionTests(unittest.TestCase):
    def setUp(self):
        handle, self.path = tempfile.mkstemp(suffix=".sqlite3")
        os.close(handle)
        self.ledger = Ledger(self.path)
        self.pipe = Pipeline(self.ledger)

    def tearDown(self):
        self.ledger.close()
        os.remove(self.path)

    def test_failed_gates_stay_in_research_without_a_promotion_row(self):
        bad = dict(GOOD, trades=4, expectancyPct=-0.2, bootstrapLower95=-0.1, winRate=0.2, profitFactor=0.4, perDay=0.1)
        result = self.pipe.consider("S2", bad, T0)
        self.assertFalse(result["entered"])
        self.assertEqual(result["stage"], "RESEARCH")
        self.assertEqual(self.ledger.counts()["promotions"], 0)
        self.assertEqual(V2_S1_MIN_DROP_PCT, 2.5)

    def test_shadow_records_for_fourteen_days_then_trial_then_live(self):
        entered = self.pipe.consider("S1", GOOD, T0, pbo_value=0.10)
        self.assertTrue(entered["entered"])
        shadow = self.pipe.policy("S1")
        self.assertTrue(shadow["push"])
        self.assertEqual(shadow["tierLabel"], "观察级·影子验证")
        watch, watch_reason = apply_release(signal(), shadow, True)
        self.assertIsNone(watch_reason)
        self.assertEqual(watch["tier_label"], "观察级·影子验证")
        self.assertTrue(watch["strategy_name_zh"].startswith("【观察级·影子验证】"))
        self.assertEqual(self.ledger.counts()["promotions"], 0)
        self.pipe.note("S1", T0 + DAY)
        self.assertEqual(self.pipe.tick("S1", T0 + 13 * DAY)["stage"], "SHADOW")
        self.assertEqual(self.ledger.counts()["promotions"], 0)
        done = self.pipe.tick("S1", T0 + V2_SHADOW_MS)
        self.assertEqual(done["action"], "SHADOW_COMPLETE")
        self.assertEqual(self.ledger.promotions()[0]["action"], "SHADOW_COMPLETE")
        trial = self.pipe.policy("S1")
        self.assertTrue(trial["push"])
        self.assertEqual(trial["tierLabel"], "试运行")
        stamped, reason = apply_release(signal(), trial, False)
        self.assertIsNone(reason)
        self.assertEqual(stamped["tier_label"], "试运行")
        self.assertTrue(stamped["strategy_name_zh"].startswith("【试运行】"))
        live = self.pipe.tick("S1", T0 + V2_SHADOW_MS + V2_TRIAL_MS)
        self.assertEqual(live["action"], "TRIAL_COMPLETE")
        self.assertEqual(self.pipe.policy("S1")["tierLabel"], "交易级")
        paused, pause_reason = apply_release(signal(), self.pipe.policy("S1"), True)
        self.assertIsNone(paused)
        self.assertEqual(pause_reason, "交易级暂停，熔断中")
        self.assertEqual(len(self.ledger.promotions()), 2)
        again = self.pipe.tick("S1", T0 + V2_SHADOW_MS + V2_TRIAL_MS)
        self.assertFalse(again["changed"])
        self.assertEqual(len(self.ledger.promotions()), 2)
        self.assertEqual(V2_S1_MIN_DROP_PCT, 2.5)

    def test_empty_shadow_window_does_not_promote(self):
        self.pipe.consider("S3", GOOD, T0, pbo_value=0.10)
        result = self.pipe.tick("S3", T0 + V2_SHADOW_MS)
        self.assertEqual(result["stage"], "SHADOW")
        self.assertEqual(self.ledger.counts()["promotions"], 0)

    def test_rollback_on_expectancy_and_drawdown_and_not_during_shadow(self):
        self.pipe.consider("S4", GOOD, T0, pbo_value=0.10)
        self.pipe.note("S4", T0)
        held = self.pipe.tick("S4", T0 + DAY, trades=[{"netPct": -1, "r": -7}])
        self.assertEqual(held["stage"], "SHADOW")
        self.assertNotIn("action", held)
        self.assertEqual(self.ledger.counts()["promotions"], 0)
        self.pipe.tick("S4", T0 + V2_SHADOW_MS)
        losing = [{"netPct": -0.2, "r": -0.1} for _ in range(30)]
        rolled = self.pipe.tick("S4", T0 + V2_SHADOW_MS + DAY, trades=losing)
        self.assertEqual(rolled["action"], "ROLLBACK")
        self.assertEqual(rolled["reason"], "最近 30 笔期望值小于 0")
        self.assertEqual(self.pipe.policy("S4")["tierLabel"], "观察级·未验证")
        self.pipe.consider("S2", GOOD, T0, pbo_value=0.10)
        self.pipe.note("S2", T0)
        self.pipe.tick("S2", T0 + V2_SHADOW_MS)
        deep = self.pipe.tick("S2", T0 + V2_SHADOW_MS + DAY, trades=[{"netPct": -1, "r": -2}] * 4)
        self.assertEqual(deep["reason"], "回撤超过 6R")
        self.assertGreater(drawdown_r([-2, -2, -2, -1]), 6)

    def test_s5_never_pushes_and_adjustments_stay_unapplied(self):
        self.assertFalse(push_policy("LIVE", "S5")["push"])
        blocked, reason = apply_release(signal("S5"), push_policy("RESEARCH", "S5"))
        self.assertIsNone(blocked)
        self.assertIn("S5", reason)
        self.assertFalse(accept_adjustment({"stopPct": 2.0, "frictionPct": 0.1})["applied"])
        self.assertEqual(accept_adjustment({"stopPct": 2.0, "frictionPct": 0.1})["reason"], "UNLEARNABLE")
        self.assertFalse(accept_adjustment({"frictionPct": 0.24, "stopPct": 0.5, "holdMinutes": 360})["applied"])

    def test_meta_label_proposal_does_not_move_module_parameters(self):
        short = fit_meta_label([{"netPct": 0.2, "openedMs": T0, "closedMs": T0 + DAY, "features": {}}])
        self.assertEqual(short["status"], "INSUFFICIENT")
        self.assertFalse(short["applied"])
        self.assertLess(short["samples"], V2_L1_MIN_SAMPLES)
        rows = []
        step = int(400 * DAY / 219)
        for index in range(220):
            opened = T0 + index * step
            rows.append({
                "module": "S1", "netPct": 0.3 if index % 3 else -0.15,
                "openedMs": opened, "closedMs": opened + 2 * 3600_000,
                "features": {"envScore": 20 + index % 7, "stopPct": 0.4 + (index % 5) * 0.05, "netRr": 1.1,
                             "volumeMultiple": 1 + index % 3, "rsi15Min": 40, "derivativePoints": index % 4},
            })
        fitted = self.pipe.store_l1(rows, T0)
        self.assertEqual(fitted["status"], "FIT")
        self.assertFalse(fitted["applied"])
        proposal = fitted["proposal"]
        self.assertGreaterEqual(proposal["pThreshold"], 0.50)
        self.assertLessEqual(proposal["pThreshold"], 0.70)
        self.assertGreaterEqual(proposal["entryOffsetPct"], -0.10)
        self.assertLessEqual(proposal["entryOffsetPct"], 0.10)
        self.assertGreaterEqual(proposal["stopBufferPct"], 0)
        self.assertLessEqual(proposal["stopBufferPct"], 0.20)
        self.assertEqual(self.ledger.counts()["promotions"], 0)
        self.assertEqual(V2_S1_MIN_DROP_PCT, 2.5)
        self.assertFalse(self.pipe.status(T0)["l1"]["applied"])

    def test_missing_pbo_does_not_enter_shadow(self):
        result = self.pipe.consider("S1", GOOD, T0)
        self.assertFalse(result["entered"])
        self.assertTrue(any(gap.startswith("PBO") for gap in result["promotion"]["gaps"]))

    def test_restart_does_not_write_a_second_l1_the_same_utc_day(self):
        self.pipe.maintain([], T0)
        first = self.ledger._one("SELECT count(*) AS n FROM l1_reports")["n"]
        restarted = Pipeline(self.ledger)
        restarted.maintain([], T0 + 1_000)
        second = self.ledger._one("SELECT count(*) AS n FROM l1_reports")["n"]
        self.assertEqual(first, 1)
        self.assertEqual(second, 1)


if __name__ == "__main__":
    unittest.main()
