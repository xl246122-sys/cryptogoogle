import unittest

from cryptog.config import V2_DERIVATIVE_POINTS
from cryptog.derivatives import score_confirmation


class DerivativeScoreTests(unittest.TestCase):
    def test_each_condition_adds_eight_and_missing_data_adds_nothing(self):
        self.assertEqual(score_confirmation(None)["points"], 0)
        self.assertEqual(score_confirmation({"status": "unavailable"})["status"], "unavailable")
        one = score_confirmation({"oi_change_1h_pct": -3, "funding_rate": -0.00009, "taker_sell_ratio": 1.49})
        self.assertEqual(one["tags"], ["OI_DROP"])
        self.assertEqual(one["points"], V2_DERIVATIVE_POINTS)
        all_three = score_confirmation({"oi_change_1h_pct": -3.1, "funding_rate": -0.0001, "taker_sell_ratio": 1.5})
        self.assertEqual(all_three["points"], 3 * V2_DERIVATIVE_POINTS)
        self.assertEqual(score_confirmation({"oi_change_1h_pct": -2.99})["points"], 0)
        dirty = score_confirmation({"oi_change_1h_pct": float("nan"), "funding_rate": float("inf"), "taker_sell_ratio": float("nan")})
        self.assertEqual(dirty["points"], 0)
        self.assertIsNone(dirty["oi_change_1h_pct"])
        self.assertIsNone(dirty["funding_rate"])


if __name__ == "__main__":
    unittest.main()
