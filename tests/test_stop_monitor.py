import unittest

from cryptog.stop_monitor import classify_exit
from cryptog.storage import EventStore
from cryptog.v2_tracker import V2Tracker


def call(**overrides):
    args = dict(bid=100, now_ms=10_000, entry=100, entry_at=0, stop=99, tp1=102, tp2=104,
                invalidation=99.4, reclaim=100.5, breakeven=100.24, sold=False,
                max_hold_minutes=360, time_stop_minutes=90, time_stop_progress_r=0.3,
                m1=None, m15=None, h1=None, fresh=True)
    args.update(overrides)
    return classify_exit(**args)


class StopMonitorTests(unittest.TestCase):
    def test_priority(self):
        self.assertEqual(call(now_ms=361 * 60_000)[0], "TIME_EXIT")
        self.assertEqual(call(bid=99)[0], "STOP_EXIT")
        self.assertEqual(call(bid=102)[0], "TP1_PARTIAL_EXIT")
        self.assertEqual(call(bid=99.1)[0], "STOP_NEAR_WARNING")
        m15 = [{"close_time": 900_000, "close": 100.2, "open": 100, "high": 101, "low": 100}]
        self.assertEqual(call(m15=m15, now_ms=1_000_000)[0], "STRUCTURE_WARNING")
        self.assertIn("收复价", call(m15=m15, now_ms=1_000_000)[1])
        minute = [{"open": 100, "close": 98.9, "close_time": i * 60_000} for i in range(1, 6)]
        self.assertEqual(call(m1=minute, now_ms=400_000)[0], "ENV_EXIT")
        self.assertEqual(call(now_ms=91 * 60_000, bid=100.05)[0], "TIME_STOP_EXIT")
        self.assertIsNone(call(fresh=False, now_ms=1_000))

    def test_shadow_watch_does_not_settle(self):
        store = EventStore(":memory:")
        tracker = V2Tracker(store)
        signal = {"alert_id": "s", "module": "S1", "entry_price": 100, "stop_loss": 99,
                  "target_tp1": 102, "target_tp2": 104, "timestamp": 0, "invalidation_price": 99.4,
                  "reclaim_price": 100.5}
        self.assertTrue(tracker.open(signal))
        first = tracker.watch(99, 1_000, {})
        self.assertEqual(first[0]["kind"], "STOP_EXIT")
        self.assertEqual(tracker.watch(99, 2_000, {}), [])
        self.assertEqual(tracker.open_count(), 1)


if __name__ == "__main__":
    unittest.main()
