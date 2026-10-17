import unittest

from cryptog.validation import (
    assign_fold, deflated_sharpe, early_recall, norm_ppf, pbo, promotion_decision, unlearnable_gaps,
)


class ValidationTests(unittest.TestCase):
    def test_inverse_normal_and_single_trial_sharpe(self):
        self.assertAlmostEqual(norm_ppf(0.975), 1.95996398454, places=6)
        series = [0.2, -0.1, 0.3, 0.1, -0.05, 0.15]
        self.assertGreater(deflated_sharpe(series, n_trials=1), 0.5)
        self.assertLess(deflated_sharpe(series, n_trials=500), deflated_sharpe(series, n_trials=1))

    def test_purged_split_and_recall(self):
        self.assertEqual(assign_fold(1_000, 2_000, 10_000, 1_000), "IS")
        self.assertEqual(assign_fold(9_500, 10_500, 10_000, 1_000), "PURGED")
        self.assertEqual(assign_fold(10_000, 11_000, 10_000, 1_000), "OOS")
        waves = [{"start": 0, "end": 90}, {"start": 100, "end": 190}]
        self.assertEqual(early_recall(waves, [10, 180]), 0.5)

    def test_promotion_and_hard_constraints(self):
        good = {"trades": 80, "expectancyPct": 0.20, "bootstrapLower95": 0.05, "winRate": 0.56,
                "profitFactor": 1.40, "perDay": 1.2, "dsr": 0.2}
        missing = promotion_decision(good, n_trials=1)
        self.assertFalse(missing["passes"])
        self.assertTrue(any(gap.startswith("PBO") for gap in missing["gaps"]))
        self.assertTrue(promotion_decision(good, n_trials=1, pbo_value=0.10)["passes"])
        self.assertFalse(promotion_decision(good, n_trials=1, pbo_value=0.30)["passes"])
        bad = dict(good, trades=10, expectancyPct=-0.2, bootstrapLower95=-0.1, winRate=0.4, profitFactor=0.8, perDay=0.1)
        self.assertFalse(promotion_decision(bad, n_trials=1)["passes"])
        self.assertTrue(unlearnable_gaps({"stopPct": 1.5, "frictionPct": 0.11, "holdMinutes": 400, "aiWritesPrices": True}))

    def test_identical_rules_are_not_overfit(self):
        column = [0.01, -0.02, 0.03, 0.0, 0.02, -0.01, 0.01, 0.02]
        self.assertEqual(pbo([column, list(column)], slices=4), 0.0)


if __name__ == "__main__":
    unittest.main()
