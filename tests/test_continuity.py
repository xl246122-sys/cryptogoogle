import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from cryptog.config import V2_FRICTION_PCT, V2_S1_MIN_DROP_PCT
from cryptog.continuity import Continuity, month_key, previous_month, previous_quarter, quarter_key
from cryptog.ledger import Ledger

CST = timezone(timedelta(hours=8))


def at(year, month, day, hour=12) -> int:
    return int(datetime(year, month, day, hour, tzinfo=CST).timestamp() * 1000)


def fill(side, quote, price, when, fee=0.10):
    return {"side": side, "quote": quote, "fill": price, "fee_pct": fee, "executedAtMs": when}


def sample(score, net, closed):
    return {"module": "S1", "netPct": net, "closedMs": closed, "features": {"envScore": score}}


class ContinuityTests(unittest.TestCase):
    def setUp(self):
        handle, self.path = tempfile.mkstemp(suffix=".sqlite3")
        os.close(handle)
        self.ledger = Ledger(self.path)
        self.job = Continuity(self.ledger)

    def tearDown(self):
        self.ledger.close()
        os.remove(self.path)

    def test_month_and_quarter_follow_beijing_time(self):
        now = at(2026, 10, 17)
        self.assertEqual(month_key(now), "2026-10")
        self.assertEqual(previous_month(now), "2026-09")
        self.assertEqual(quarter_key(now), "2026-Q4")
        self.assertEqual(previous_quarter(now), "2026-Q3")
        self.assertEqual(previous_quarter(at(2026, 1, 2)), "2025-Q4")

    def test_fills_can_raise_the_working_cost_and_cannot_lower_the_floor(self):
        now = at(2026, 10, 17)
        expensive = [
            fill("BUY", 100, 100.08, at(2026, 9, 15)),
            fill("SELL", 100, 99.92, at(2026, 9, 16)),
            fill("BUY", 100, 100.20, at(2026, 10, 2)),
        ]
        report = self.job.maintain(now, fills=expensive, samples=[])
        self.assertGreater(report["cost"]["frictionPct"], 0.24)
        self.assertEqual(report["cost"]["floorPct"], 0.24)
        self.assertEqual(report["cost"]["source"], "FILLS")
        self.assertFalse(report["cost"]["applied"])
        self.assertEqual(V2_FRICTION_PCT, 0.24)
        self.assertEqual(V2_S1_MIN_DROP_PCT, 2.5)
        self.assertEqual(self.ledger.counts()["promotions"], 0)
        self.assertEqual(self.ledger.counts()["ai_reviews"], 0)
        self.assertFalse(report["weeklyHypothesesApplied"])
        cheap = self.job.maintain(at(2026, 11, 2), fills=[
            fill("BUY", 100, 100.01, at(2026, 10, 3)),
            fill("SELL", 101, 100.99, at(2026, 10, 4)),
        ], samples=[])
        self.assertEqual(cheap["cost"]["frictionPct"], 0.24)
        self.assertEqual(cheap["cost"]["source"], "FLOOR")
        empty = self.job.maintain(at(2026, 12, 2), fills=[], samples=[])
        self.assertEqual(empty["cost"]["source"], "PRIOR")
        self.assertEqual(empty["cost"]["frictionPct"], 0.24)

    def test_a_month_is_written_once_and_the_open_quarter_waits_out_the_hold(self):
        now = at(2026, 10, 1, 1)
        first = self.job.maintain(now, fills=[], samples=[])
        self.assertEqual(first["environment"]["status"], "OPEN")
        self.assertFalse(first["environment"]["applied"])
        self.assertIsNone(self.ledger._one("SELECT id FROM environment_reports"))
        again = self.job.maintain(now, fills=[fill("BUY", 100, 101, at(2026, 9, 2))], samples=[])
        self.assertEqual(again["cost"]["source"], "PRIOR")
        self.assertEqual(self.ledger._one("SELECT count(*) AS n FROM cost_reports")["n"], 1)
        self.assertEqual(self.job.status(now)["environmentOpen"], "2026-Q3")

    def test_quarterly_boundary_is_held_inside_the_published_span(self):
        closed = at(2026, 8, 10)
        rows = (
            [sample(40, 1.0, closed) for _ in range(80)]
            + [sample(5, -0.5, closed) for _ in range(80)]
            + [sample(-30, -1.0, closed) for _ in range(80)]
        )
        early = self.job.maintain(at(2026, 10, 1, 1), fills=[], samples=rows)
        self.assertEqual(early["environment"]["status"], "OPEN")
        report = self.job.maintain(at(2026, 10, 17), fills=[], samples=rows)
        env = report["environment"]
        self.assertEqual(env["status"], "HELD")
        self.assertEqual(env["cutoff"], 10)
        self.assertEqual(env["priorCutoff"], 0)
        self.assertFalse(env["applied"])
        self.assertLessEqual(abs(env["cutoff"]), 20)
        self.assertEqual(V2_S1_MIN_DROP_PCT, 2.5)
        self.assertEqual(self.ledger.counts()["promotions"], 0)
        second = self.job.maintain(at(2026, 10, 20), fills=[], samples=[sample(40, -5, closed) for _ in range(240)])
        self.assertEqual(second["environment"]["cutoff"], 10)
        self.assertEqual(self.ledger._one("SELECT count(*) AS n FROM environment_reports")["n"], 1)
        view = self.job.status(at(2026, 10, 20))
        self.assertFalse(view["environment"]["applied"])
        self.assertEqual(view["environment"]["cutoff"], 10)
        self.assertFalse(view["weeklyHypothesesApplied"])

    def test_a_short_quarter_stays_insufficient_and_still_does_not_move_the_prior(self):
        rows = [sample(10, 0.2, at(2026, 8, 3)) for _ in range(12)]
        report = self.job.maintain(at(2026, 10, 17), fills=[], samples=rows)["environment"]
        self.assertEqual(report["status"], "INSUFFICIENT")
        self.assertIsNone(report["cutoff"])
        self.assertEqual(report["priorCutoff"], 0)
        self.assertFalse(report["applied"])


if __name__ == "__main__":
    unittest.main()
