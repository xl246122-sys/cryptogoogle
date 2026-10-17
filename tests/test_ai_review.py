import json
import os
import re
import tempfile
import time
import unittest

from cryptog.ai_review import (
    brief, build_daily_review, check_hypothesis, cst_date, day_bounds, decorate_exit_message, detect_anomalies,
    explain_signal, maintain, propose_hypotheses, review_signal, submit_hypotheses, veto_blocks, week_key,
)
from cryptog.config import V2_RULE_VERSION, V2_S1_MIN_DROP_PCT
from cryptog.ledger import Ledger
from cryptog.notifications import NotificationWorker
from cryptog.storage import EventStore
from cryptog.v2_tracker import veto_audit


def signal():
    return {
        "rule_version": V2_RULE_VERSION, "module": "S2", "tier": "WATCH",
        "entry_price": 81000, "stop_loss": 80700, "target_tp1": 82000,
        "stop_loss_pct": 0.37, "net_tp1": 1.0, "net_rr": 1.6,
        "v2": {"env": {"states": {"d1": "ABOVE_99", "h4": "DOWN", "h1": "DOWN"}, "score": -32},
               "features": {"support": "1D 布林下轨", "wickToBody": 2.1}, "spreadPct": 0.001,
               "derivatives": {"status": "unavailable"}},
    }


class AIReviewTests(unittest.TestCase):
    def test_brief_has_no_absolute_price(self):
        text = json.dumps(brief(signal()))
        self.assertNotIn("81000", text)
        self.assertNotIn("entry_price", text)

    def test_timeout_and_bad_json_pass(self):
        def slow(_payload):
            time.sleep(2)
            return {"verdict": "VETO", "tags": [], "note": "来不及", "confidence": 1}
        self.assertEqual(review_signal(signal(), post=slow, timeout=0.05)["verdict"], "PASS")
        self.assertEqual(review_signal(signal(), post=slow, timeout=0.05)["fallback"], "TIMEOUT")
        self.assertEqual(review_signal(signal(), post=lambda _p: {"verdict": "MAYBE"})["fallback"], "FORMAT")
        self.assertEqual(review_signal(signal(), post=lambda _p: {"verdict": "VETO", "tags": [], "note": "看到79800就否决", "confidence": 0.2})["fallback"], "FORMAT")

    def test_valid_veto_is_kept_and_disabled_review_passes(self):
        review = review_signal(signal(), post=lambda _p: {"verdict": "否决", "tags": ["环境逆势"], "note": "四小时仍是空头", "confidence": 0.66})
        self.assertEqual(review["verdict"], "VETO")
        self.assertEqual(review["note"], "四小时仍是空头")
        self.assertIsNone(review["fallback"])
        self.assertEqual(review_signal(signal(), enabled=False)["verdict"], "PASS")
        self.assertEqual(review_signal(signal())["fallback"], "MISSING_KEY")

    def test_timeout_and_bad_format_do_not_cancel_the_push(self):
        store = EventStore(":memory:")
        worker = NotificationWorker(store, None, None, lambda *_args: True, False)
        worker.review_timeout = 0.05

        def slow(_payload):
            time.sleep(1)
            return {"verdict": "VETO", "tags": [], "note": "来不及", "confidence": 1}

        worker.review_post = slow
        pushed = worker._review("slow", signal(), 1_700_000_000_000)
        self.assertEqual(pushed["ai_verdict"], "PASS")
        self.assertFalse(veto_blocks({"verdict": pushed["ai_verdict"], "vetoEnabled": True}))
        worker.review_timeout = 2
        worker.review_post = lambda _payload: {"verdict": "MAYBE"}
        self.assertEqual(worker._review("bad", signal(), 1_700_000_000_000)["ai_verdict"], "PASS")

    def test_disabled_veto_still_records_the_opinion_and_lets_the_push_through(self):
        closed = [{"verdict": "VETO", "r": 0.2}] * 100 + [{"verdict": "PASS", "r": -0.4}] * 20
        audit = veto_audit(closed)
        self.assertFalse(audit["vetoEnabled"])
        self.assertFalse(veto_blocks({"verdict": "VETO", "vetoEnabled": audit["vetoEnabled"]}))
        store = EventStore(":memory:")
        worker = NotificationWorker(store, None, None, lambda *_args: True, False)
        worker.tracker = _Audit(audit)
        worker.review_post = lambda _payload: {"verdict": "否决", "tags": ["环境逆势"], "note": "四小时仍是空头", "confidence": 0.4}
        pushed = worker._review("kept", signal(), 1_700_000_000_000)
        self.assertEqual(pushed["ai_verdict"], "VETO")
        self.assertEqual(worker.tracker.saved, [("kept", "VETO")])
        worker.tracker = None
        self.assertIsNone(worker._review("blocked", signal(), 1_700_000_000_000))

    def test_anomalies_and_commentary_cite_only_engine_numbers(self):
        flush = signal()
        flush["module"] = "S1"
        flush["v2"]["features"] = {"dropPct": 3.2}
        flush["v2"]["derivatives"] = {"oi_change_1h_pct": -4.2, "funding_rate": -0.0002, "taker_sell_ratio": 1.8}
        found = detect_anomalies(flush)
        self.assertEqual(found["flags"], ["LIQUIDATION_FLUSH", "FUNDING_EXTREME", "OI_DROP"])
        text = explain_signal(flush)
        self.assertNotIn("81000", text)
        self._numbers_are_cited(text, found["cited"])
        self.assertIn("强平潮", text)
        quiet = signal()
        self.assertEqual(detect_anomalies(quiet)["flags"], ["FALSE_BREAK"])
        note = explain_signal(quiet)
        self.assertNotIn("81000", note)
        self._numbers_are_cited(note, detect_anomalies(quiet)["cited"])
        self.assertEqual(detect_anomalies({"v2": {"derivatives": {"status": "unavailable"}}})["flags"], [])
        self.assertEqual(decorate_exit_message("STOP_EXIT", "成交价已到止损，立即卖出。", "bad"), "成交价已到止损，立即卖出。")
        self.assertIn("0.37", decorate_exit_message("STOP_EXIT", "成交价已到止损，立即卖出。", {"stop_loss_pct": 0.37}))

    def test_daily_review_reads_the_paper_and_system_gap(self):
        handle, path = tempfile.mkstemp(suffix=".sqlite3")
        os.close(handle)
        ledger = Ledger(path)
        try:
            from test_ledger import T, fill, signal as plan, stop_bar

            row = plan()
            ledger.record_candidate(row)
            ledger.store.upsert_klines("BTCUSDT", "1m", [stop_bar()])
            ledger.record_buy(fill("buy-1", "BUY", T, 100.0), signal_id=row["alert_id"])
            ledger.record_sell(fill("sell-1", "SELL", T + 60_000, 100.4))
            start, end = day_bounds(T + 60_000)
            review = build_daily_review(ledger.closed_twins(start, end), cst_date(T).isoformat())
            trade = review["trades"][0]
            self.assertAlmostEqual(trade["userNetPct"], 0.16)
            self.assertAlmostEqual(trade["systemNetPct"], -0.74)
            self.assertAlmostEqual(trade["gapPct"], 0.9)
            self.assertEqual(trade["lossAttribution"], "STOP")
            self.assertNotIn("100.4", review["summary"])
            self.assertIn("0.16", review["summary"])
            self.assertIn("止损", review["summary"])
            state = maintain(ledger, {"vetoEnabled": False, "vetoed": 100, "passed": 20, "vetoedMeanR": 0.1, "passedMeanR": -0.2}, T + 60_000)
            maintain(ledger, {"vetoEnabled": False, "vetoed": 100, "passed": 20, "vetoedMeanR": 0.1, "passedMeanR": -0.2}, T + 61_000, state=state)
            day = state["day"]
            self.assertEqual(ledger.counts()["ai_reviews"], 2)
            stored = json.loads(ledger._one("SELECT payload FROM ai_reviews WHERE id=?", (f"daily:{day}",))["payload"])
            self.assertEqual(stored["trades"][0]["lossAttribution"], "STOP")
            audit = json.loads(ledger._one("SELECT payload FROM ai_reviews WHERE id=?", (f"veto:{day}:0",))["payload"])
            self.assertFalse(audit["vetoEnabled"])
        finally:
            ledger.close()
            os.remove(path)

    def test_hypotheses_are_checked_and_do_not_change_rules(self):
        self.assertEqual(propose_hypotheses(lambda _payload: time.sleep(1), timeout=0.05)["fallback"], "TIMEOUT")
        self.assertEqual(propose_hypotheses(lambda _payload: {"nope": 1})["fallback"], "FORMAT")
        samples = []
        start = 1_700_000_000_000
        for index in range(60):
            opened = start + index * 12 * 3_600_000
            samples.append({"module": "S2", "netPct": 0.2, "openedMs": opened, "closedMs": opened + 3_600_000,
                            "features": {"wickToBody": 2}})
        passed = check_hypothesis(samples, {"module": "S2", "feature": "wickToBody", "op": ">=", "value": 1.5, "claim": "影线更长"})
        self.assertEqual(passed["status"], "CHECKED")
        self.assertFalse(passed["promotion"]["passes"])
        self.assertTrue(any(gap.startswith("PBO") for gap in passed["promotion"]["gaps"]))
        self.assertFalse(passed["applied"])
        handle, path = tempfile.mkstemp(suffix=".sqlite3")
        os.close(handle)
        ledger = Ledger(path)
        try:
            from test_ledger import T, fill, signal as plan, stop_bar

            row = plan()
            ledger.record_candidate(row)
            ledger.store.upsert_klines("BTCUSDT", "1m", [stop_bar()])
            ledger.record_buy(fill("buy-1", "BUY", T, 100.0), signal_id=row["alert_id"])
            ledger.record_sell(fill("sell-1", "SELL", T + 60_000, 100.4))
            good = {"module": "S2", "feature": "wickToBody", "op": ">=", "value": 1.5, "claim": "影线更长"}
            stored = submit_hypotheses(ledger, [
                {**good, "frictionPct": 0.01},
                good, dict(good, claim="影线仍长"),
                dict(good, claim="影线阈值放宽", value=1.0),
                dict(good, claim="第四条不检验"),
            ], T)
            statuses = [item["status"] for item in stored["stored"]]
            self.assertEqual(statuses, ["REJECTED", "CHECKED", "CHECKED", "CHECKED", "WEEKLY_CAP"])
            self.assertEqual(stored["stored"][0]["reason"], "UNLEARNABLE")
            self.assertFalse(any(item.get("applied") for item in stored["stored"]))
            self.assertEqual(ledger.hypothesis_count(week_key(T)), 3)
            self.assertEqual(ledger.counts()["promotions"], 0)
            self.assertEqual(V2_S1_MIN_DROP_PCT, 2.5)
            calls = {"n": 0}

            def post(_payload):
                calls["n"] += 1
                return {"hypotheses": []}

            maintain(ledger, {"vetoEnabled": True}, T, post=post, state={})
            after = ledger.counts()["ai_reviews"]
            maintain(ledger, {"vetoEnabled": True}, T + 1_000, post=post, state={})
            self.assertEqual(calls["n"], 0)
            self.assertEqual(ledger.counts()["ai_reviews"], after)
        finally:
            ledger.close()
            os.remove(path)

    def _numbers_are_cited(self, text, cited):
        allowed = set()
        for value in cited.values():
            if isinstance(value, str):
                allowed.update(re.findall(r"-?\d+(?:\.\d+)?", value))
        for number in re.findall(r"-?\d+(?:\.\d+)?", text):
            self.assertIn(number, allowed)


class _Audit:
    def __init__(self, audit):
        self.audit_row = audit
        self.saved = []

    def audit(self):
        return self.audit_row

    def set_verdict(self, alert_id, verdict):
        self.saved.append((alert_id, verdict))


if __name__ == "__main__":
    unittest.main()
