import unittest

from cryptog.barriers import label_v2, triple_barrier


def bar(at, low, high, close, step=300_000):
    return {"time": at, "close_time": at + step - 1, "open": close, "high": high, "low": low, "close": close, "volume": 1}


class BarrierTests(unittest.TestCase):
    def test_stop_wins_when_the_same_bar_also_touches_the_target(self):
        marked = triple_barrier([bar(0, 90, 110, 100)], 100, 95, 105, 0, 3_600_000, 0.24)
        self.assertEqual(marked["barrier"], "STOP")
        self.assertEqual(marked["label"], -1)
        self.assertAlmostEqual(marked["netPct"], (95 / 100 - 1) * 100 - 0.24)

    def test_target_and_vertical(self):
        taken = triple_barrier([bar(0, 99, 106, 105)], 100, 95, 105, 0, 3_600_000, 0.24)
        self.assertEqual(taken["barrier"], "TAKE")
        quiet = triple_barrier([bar(0, 99.5, 100.5, 100.2)], 100, 95, 105, 0, 60_000, 0.24)
        self.assertEqual(quiet["barrier"], "VERTICAL")
        self.assertEqual(quiet["label"], 0)

    def test_v2_path_stops_out_the_whole_position(self):
        at = 1_700_000_000_000
        signal = {"alert_id": "b", "module": "S1", "entry_price": 100, "stop_loss": 99.4,
                  "target_tp1": 101.2, "target_tp2": 102, "timestamp": at}
        labeled = label_v2(signal, [bar(at, 99.0, 100.1, 99.5)], [])
        self.assertEqual(labeled["outcome"], "STOP")
        self.assertLess(labeled["pnlPct"], 0)


if __name__ == "__main__":
    unittest.main()
