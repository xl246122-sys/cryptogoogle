import unittest

from cryptog.storage import EventStore
from cryptog.v2_tracker import V2Tracker, advance, breaker_state, open_state

M1 = 60_000


def signal(name, entry=100, stop=99.5, tp1=101.2, tp2=102, at=1_700_000_000_000):
    return {"alert_id": name, "module": "S2", "entry_price": entry, "stop_loss": stop,
            "target_tp1": tp1, "target_tp2": tp2, "timestamp": at}


def bar(at, low, high, close):
    return {"time": at, "close_time": at + M1 - 1, "open": close, "high": high, "low": low, "close": close, "volume": 1}


class TrackerTests(unittest.TestCase):
    def test_stop_is_a_full_loss_and_two_stops_pause_trade_tier(self):
        state = open_state(signal("a"))
        advance(state, [bar(state["openedAt"], 99.4, 100.1, 99.6)], [])
        self.assertEqual(state["outcome"], "STOP")
        self.assertEqual(state["r"], -1.0)
        later = state["closedAt"] + 1000
        second = dict(state, closedAt=later, verdict="PASS", outcome="STOP", r=-1.0)
        paused = breaker_state([state, second], later + 1000)
        self.assertGreater(paused["pausedUntil"], later)
        vetoed = dict(state, verdict="VETO", outcome="STOP", r=-1.0)
        self.assertEqual(breaker_state([vetoed], later)["pausedUntil"], 0)

    def test_store_round_trip(self):
        store = EventStore(":memory:")
        tracker = V2Tracker(store)
        opened = signal("BTCUSDT_S2_1")
        self.assertTrue(tracker.open(opened))
        self.assertFalse(tracker.open(opened))
        state = open_state(opened)
        closed = tracker.step([bar(state["openedAt"], 99.4, 100.1, 99.6)], [])
        self.assertEqual(closed[0]["outcome"], "STOP")
        self.assertEqual(tracker.open_count(), 0)


if __name__ == "__main__":
    unittest.main()
