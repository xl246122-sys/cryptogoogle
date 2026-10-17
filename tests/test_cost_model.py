import unittest

from cryptog.cost_model import calibrate, position_fraction_pct, round_trip_pct


class CostModelTests(unittest.TestCase):
    def test_floor_and_position_size(self):
        self.assertEqual(round_trip_pct(False), 0.24)
        self.assertEqual(round_trip_pct(True), 0.19)
        self.assertAlmostEqual(position_fraction_pct(0.50), 0.50 / 0.74 * 100)

    def test_fills_can_raise_the_cost_and_cannot_lower_the_floor(self):
        cheap = calibrate([
            {"side": "BUY", "quote": 100, "fill": 100.01, "fee_pct": 0.10},
            {"side": "SELL", "quote": 101, "fill": 100.99, "fee_pct": 0.10},
        ])
        self.assertEqual(cheap["frictionPct"], 0.24)
        self.assertEqual(cheap["source"], "FLOOR")
        expensive = calibrate([
            {"side": "BUY", "quote": 100, "fill": 100.08, "fee_pct": 0.10},
            {"side": "SELL", "quote": 100, "fill": 99.92, "fee_pct": 0.10},
        ])
        self.assertGreater(expensive["frictionPct"], 0.24)
        self.assertEqual(expensive["source"], "FILLS")
        discounted = calibrate([], bnb_discount=True)
        self.assertEqual(discounted["frictionPct"], 0.19)


if __name__ == "__main__":
    unittest.main()
