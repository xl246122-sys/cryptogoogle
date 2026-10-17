import unittest
from datetime import date, datetime, timedelta, timezone

from cryptog.engine_v2 import detect_s5, us_cash_open_utc

M15 = 900_000


def session_bars(end_day: date, volume_at_end: float, close_up: bool):
    start = datetime(end_day.year, end_day.month, end_day.day, tzinfo=timezone.utc) - timedelta(days=50)
    opened = us_cash_open_utc(end_day)
    end = datetime(end_day.year, end_day.month, end_day.day, opened[0], opened[1], tzinfo=timezone.utc) + timedelta(minutes=15)
    cursor = int(start.timestamp() * 1000)
    stop = int(end.timestamp() * 1000)
    bars = []
    while cursor <= stop:
        moment = datetime.fromtimestamp(cursor / 1000, timezone.utc)
        window = us_cash_open_utc(moment.date())
        in_window = window is not None and (moment.hour, moment.minute) in (window, (window[0], window[1] + 15))
        last = moment.date() == end_day and in_window
        price = 101 if last and close_up and (moment.hour, moment.minute) == (window[0], window[1] + 15) else 100
        bars.append({"time": cursor, "close_time": cursor + M15 - 1, "open": 100, "high": max(100, price),
                     "low": 100, "close": price, "volume": volume_at_end if last else (100 if in_window else 10)})
        cursor += M15
    return bars


class SessionMomentumTests(unittest.TestCase):
    def test_daylight_and_standard_open(self):
        self.assertEqual(us_cash_open_utc(date(2026, 10, 16)), (13, 30))
        self.assertEqual(us_cash_open_utc(date(2026, 1, 15)), (14, 30))
        self.assertIsNone(us_cash_open_utc(date(2026, 10, 17)))

    def test_research_signal_is_not_a_buy(self):
        found = detect_s5(session_bars(date(2026, 10, 16), 200, True))
        self.assertFalse(found["push"])
        self.assertEqual(found["tier"], "RESEARCH")
        self.assertGreaterEqual(found["features"]["volumeMultiple"], 1.5)
        self.assertIsNone(detect_s5(session_bars(date(2026, 10, 16), 110, True)))
        self.assertIsNone(detect_s5(session_bars(date(2026, 10, 16), 200, False)))
        winter = detect_s5(session_bars(date(2026, 1, 15), 200, True))
        self.assertEqual(winter["module"], "S5")
        self.assertIn("14:30", winter["reason"])


if __name__ == "__main__":
    unittest.main()
