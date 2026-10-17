import json
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path

from cryptog.cost_risk import notification_ttl_ms
from cryptog.short_horizon import FLUSH, aggregate, classify

CST = timezone(timedelta(hours=8))
FIXTURE = Path(__file__).parent / "fixtures" / "btc_20261011_17.json"


def stamp(day, hour, minute=0):
    return int(datetime(2026, 10, day, hour, minute, tzinfo=CST).timestamp() * 1000)


class ShortHorizonTests(unittest.TestCase):
    def replay(self):
        data = json.loads(FIXTURE.read_text(encoding="utf-8"))
        ten = aggregate(data["5m"], 300_000, 600_000)
        thirty = aggregate(data["15m"], 900_000, 1_800_000)
        found = []
        for bar in ten:
            now = bar["close_time"] + 1000
            setup = classify(
                [item for item in ten if item["close_time"] < now],
                [item for item in thirty if item["close_time"] < now],
                [item for item in data["1h"] if item["close_time"] < now],
                bar["close"],
                now,
            )
            if setup:
                found.append(setup)
        return found

    def test_october_flush_once_and_current_grind_silent(self):
        found = self.replay()
        flushes = [item for item in found if item["module"] == FLUSH and stamp(15, 21, 40) <= item["confirmation_ms"] <= stamp(15, 22, 20)]
        self.assertEqual(len(flushes), 1, [(datetime.fromtimestamp(item["confirmation_ms"] / 1000, CST).isoformat(), item["module"], round(item["entry"])) for item in found])
        self.assertGreaterEqual(flushes[0]["net"], 0.59)
        self.assertGreaterEqual(flushes[0]["rr"], 1.10)
        self.assertLessEqual(flushes[0]["risk"], 1.80)
        late = [item for item in found if item["confirmation_ms"] >= stamp(17, 7)]
        self.assertEqual(late, [])

    def test_short_horizon_push_lives_past_ninety_seconds(self):
        payload = {"tradeRules": json.dumps({"ruleVersion": "short-horizon-v1"}), "expiresAt": "999"}
        self.assertEqual(notification_ttl_ms(payload, 30 * 60 * 1000), 30 * 60 * 1000)
        self.assertEqual(notification_ttl_ms({"tradeRules": "{}"}, 120_000), 90_000)


if __name__ == "__main__":
    unittest.main()
