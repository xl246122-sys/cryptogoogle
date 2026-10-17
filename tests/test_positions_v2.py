import unittest
from decimal import Decimal

from cryptog.positions import project_positions

NOW = 1_700_000_000_000


def fill(event, side="BUY", quantity=1, at=NOW, price=100):
    return {"recordType": "MANUAL_FILL", "eventId": event, "alertId": "alert",
            "fill": {"fillId": event, "positionId": "p", "side": side, "quantity": quantity,
                     "price": price, "executedAtMs": at, "commission": 0, "commissionAsset": "USDT",
                     "timeApproximate": False}}


CONTRACT = {"rule_version": "short-horizon-v2", "entry_price": 100, "stop_loss": 99.5,
            "invalidation_price": 99.7, "target_tp1": 101.2, "target_tp2": 102.4,
            "tp1_fraction": 0.5, "max_hold_minutes": 360, "breakeven_price": 100.24,
            "time_stop_minutes": 90, "time_stop_progress_r": 0.3}


def report(rows, bid, at, series=None):
    tracks = {"alert": {"signalSnapshot": CONTRACT}}
    return project_positions(rows, tracks, at, bid, at, series)[0]


class PositionV2Tests(unittest.TestCase):
    def test_stop_partial_breakeven_and_time_stop(self):
        buy = [fill("buy")]
        self.assertEqual(report(buy, 99.5, NOW + 1000)["notice"]["kind"], "STOP_EXIT")
        self.assertEqual(report(buy, 101.2, NOW + 1000)["notice"]["kind"], "TP1_PARTIAL_EXIT")
        self.assertAlmostEqual(report(buy, 101.2, NOW + 1000)["notice"]["quantity"], 0.5)
        held = [fill("buy"), fill("sell", "SELL", 0.5, NOW + 1000, 101.2)]
        self.assertEqual(report(held, 100.2, NOW + 2000)["notice"]["kind"], "BREAKEVEN_EXIT")
        self.assertEqual(report(buy, 100.05, NOW + 91 * 60_000)["notice"]["kind"], "TIME_STOP_EXIT")
        self.assertEqual(report(buy, 100.4, NOW + 361 * 60_000)["notice"]["kind"], "TIME_EXIT")


if __name__ == "__main__":
    unittest.main()
