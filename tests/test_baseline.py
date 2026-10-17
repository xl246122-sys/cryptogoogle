import unittest

from cryptog.baseline import evaluate_history, limit_fill, render_markdown


def bar(at, open_, low, high, close):
    return {"time": at, "close_time": at + 300_000 - 1, "open": open_, "high": high, "low": low,
            "close": close, "volume": 1}


class BaselineTests(unittest.TestCase):
    def test_limit_fills_inside_the_band_and_cancels_a_runaway(self):
        setup = {"trigger": {"close_time": 1_000, "close": 100}, "entry_min": 99.5, "entry_max": 100.2, "stop": 99}
        filled = limit_fill(setup, [bar(60_000, 100.5, 100.0, 100.6, 100.1)], 30 * 60_000)
        self.assertEqual(filled["price"], 100.2)
        runaway = [bar(60_000, 101, 100.6, 101.2, 101)]
        self.assertIsNone(limit_fill(setup, runaway, 30 * 60_000))

    def test_short_history_still_names_every_module(self):
        report = evaluate_history({"1d": [], "4h": [], "1h": [], "15m": [], "5m": []})
        self.assertEqual(set(report["modules"]), {"S1", "S2", "S3", "S4", "S5"})
        self.assertIn("K 线不足", render_markdown(report))


if __name__ == "__main__":
    unittest.main()
