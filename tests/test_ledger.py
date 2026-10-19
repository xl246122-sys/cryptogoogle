import os
import tempfile
import unittest

from cryptog.config import V2_FRICTION_PCT, V2_PAPER_NOTIONAL_USDT
from cryptog.ledger import FEATURE_VERSION, SUBJECTIVE, Ledger

T = 1_700_000_040_000


def signal(at=T, expires=None, verdict=None):
    row = {
        "alert_id": f"BTCUSDT_S2_{at}", "module": "S2", "tier": "WATCH", "rule_version": "short-horizon-v2",
        "entry_price": 100.0, "stop_loss": 99.5, "target_tp1": 101.2, "target_tp2": 103.0,
        "entry_min": 99.9, "entry_max": 100.2, "timestamp": at, "confirmation_time": at,
        "expires_at": at + 30 * 60_000 if expires is None else expires,
        "stop_loss_pct": 0.5, "net_tp1": 0.96, "net_rr": 1.2, "ai_verdict": verdict,
        "v2": {
            "env": {"states": {"d1": "UP", "h4": "UP", "h1": "RANGE"}, "score": 40, "gates": {"S1": True, "S2": True, "S3": False, "S4": False}, "label": "1D 多"},
            "features": {"dropPct": 2.6, "wickToBody": 1.8},
            "derivatives": {"points": 8, "oi_change_1h_pct": -3.2, "funding_rate": -0.0001, "taker_sell_ratio": 1.1},
            "spreadPct": 0.01, "sessionUtcHour": 14, "structuralStop": 99.55,
        },
    }
    return row


def fill(fid, side, at, price, position="pos-1"):
    return {
        "fillId": fid, "positionId": position, "side": side, "source": "MANUAL",
        "price": price, "quantity": 0.01, "executedAtMs": at, "timeApproximate": False,
        "commission": 0.0005, "commissionAsset": "USDT", "commissionAssetUsdtRate": None,
        "referencePrice": price, "referenceAtMs": at - 1000,
    }


def stop_bar(at=T):
    return {"time": at, "close_time": at + 59_999, "open": 100.0, "high": 100.2, "low": 99.4, "close": 99.6,
            "volume": 1.0, "taker_buy_base": 0.4, "is_closed": True}


class LedgerTests(unittest.TestCase):
    def setUp(self):
        handle, self.path = tempfile.mkstemp(suffix=".sqlite3")
        os.close(handle)
        self.ledger = Ledger(self.path)

    def tearDown(self):
        self.ledger.close()
        os.remove(self.path)

    def test_one_real_round_trip_writes_the_twin_and_the_label(self):
        plan = signal()
        self.ledger.record_candidate(plan)
        self.ledger.store.upsert_klines("BTCUSDT", "1m", [stop_bar()])
        opened = self.ledger.record_buy(fill("buy-1", "BUY", T, 100.0), signal_id=plan["alert_id"],
                                        latency={"signalToEntryMs": 2500, "receivedToEntryMs": 1800, "openedToEntryMs": 900})
        self.assertFalse(opened["subjective"])
        self.assertEqual(opened["notionalUsdt"], V2_PAPER_NOTIONAL_USDT)
        self.assertEqual(opened["signalId"], plan["alert_id"])
        paper = self.ledger.position(opened["paperTwinId"])
        system = self.ledger.position(opened["systemTwinId"])
        self.assertEqual(paper["kind"], "PAPER")
        self.assertEqual(paper["notional_usdt"], 500)
        self.assertAlmostEqual(paper["quantity"], 5.0)
        self.assertEqual(paper["entry_price"], 100.0)
        self.assertEqual(paper["opened_ms"], T)
        self.assertEqual(system["kind"], "SYSTEM")
        self.assertEqual(system["entry_price"], 100.0)
        snap = self.ledger.feature_for(opened["paperTwinId"])
        self.assertEqual(snap["version"], FEATURE_VERSION)
        self.assertGreaterEqual(len(snap["body"]["features"]), 40)
        self.assertEqual(snap["body"]["features"]["spreadPct"], 0.01)
        self.assertEqual(snap["body"]["features"]["signalToEntryMs"], 2500)
        self.assertEqual(snap["body"]["features"]["module"], "S2")
        closed = self.ledger.record_sell(fill("sell-1", "SELL", T + 60_000, 100.4))
        self.assertTrue(closed["closed"])
        self.assertEqual(closed["labelId"], "label:" + opened["systemTwinId"])
        paper = self.ledger.position(opened["paperTwinId"])
        system = self.ledger.position(opened["systemTwinId"])
        self.assertEqual(paper["exit_reason"], "USER_EXIT")
        self.assertEqual(paper["exit_price"], 100.4)
        self.assertAlmostEqual(paper["state_payload"]["userNetPct"], round((1.004 - .0005 - 1.0005) / 1.0005 * 100, 4))
        self.assertEqual(system["exit_reason"], "STOP")
        self.assertEqual(system["exit_price"], 99.5)
        label = self.ledger.label_for(opened["systemTwinId"])
        self.assertEqual(label["barrier"], "STOP")
        self.assertEqual(label["label"], -1)
        self.assertAlmostEqual(label["net_pct"], -0.74)
        self.assertAlmostEqual(label["mfe_pct"], 0.2)
        self.assertAlmostEqual(label["mae_pct"], -0.6)
        self.assertIsNone(label["tp1_minutes"])
        self.assertEqual(label["body"]["r"], -1.0)
        again = self.ledger.record_buy(fill("buy-1", "BUY", T, 100.0), signal_id=plan["alert_id"])
        self.assertEqual(again["paperTwinId"], opened["paperTwinId"])
        self.assertEqual(self.ledger.counts()["promotions"], 0)
        self.assertEqual(self.ledger.counts()["real_fills"], 2)
        self.assertGreaterEqual(self.ledger.measured_cost()["frictionPct"], V2_FRICTION_PCT)
        row = self.ledger._one("SELECT signal_id, paper_twin_id, subjective FROM real_fills WHERE fill_id='buy-1'")
        self.assertEqual(row["signal_id"], plan["alert_id"])
        self.assertEqual(row["paper_twin_id"], opened["paperTwinId"])
        self.assertEqual(row["subjective"], 0)

    def test_missing_signal_is_subjective_and_still_labels_the_user_exit(self):
        opened = self.ledger.record_buy(fill("buy-2", "BUY", T, 100.0, "pos-2"))
        self.assertTrue(opened["subjective"])
        self.assertEqual(opened["link"], SUBJECTIVE)
        self.assertIsNone(opened["systemTwinId"])
        self.assertIsNone(self.ledger.position("shadow:" + opened["paperTwinId"]))
        closed = self.ledger.record_sell(fill("sell-2", "SELL", T + 60_000, 99.0, "pos-2"))
        label = self.ledger.label_for(opened["paperTwinId"])
        self.assertEqual(label["barrier"], "USER")
        self.assertEqual(closed["labelId"], label["id"])
        self.assertLess(label["net_pct"], 0)

    def test_expired_candidate_does_not_attach(self):
        stale = signal(expires=T - 1)
        self.ledger.record_candidate(stale)
        opened = self.ledger.record_buy(fill("buy-3", "BUY", T, 100.0, "pos-3"))
        self.assertTrue(opened["subjective"])
        self.assertIsNone(opened["systemTwinId"])

    def test_nearest_open_candidate_attaches_without_an_explicit_id(self):
        plan = signal()
        self.ledger.record_candidate(plan)
        opened = self.ledger.record_buy(fill("buy-4", "BUY", T + 1000, 100.0, "pos-4"))
        self.assertEqual(opened["signalId"], plan["alert_id"])

    def test_veto_and_watch_shadows_settle_and_s5_does_not_open(self):
        plan = signal()
        opened = self.ledger.record_candidate(plan, verdict="VETO")
        self.assertEqual(self.ledger.position(opened["shadowId"])["state_payload"]["verdict"], "VETO")
        self.assertEqual(self.ledger.position(opened["shadowId"])["notional_usdt"], 500)
        closed = self.ledger.settle([stop_bar()], [])
        self.assertEqual(closed[0]["outcome"], "STOP")
        self.assertEqual(self.ledger.label_for(opened["shadowId"])["barrier"], "STOP")
        research = self.ledger.record_research({
            "module": "S5", "anchor_time": T, "trigger": {"close_time": T}, "features": {"volumeMultiple": 1.8},
        })
        self.assertIsNone(self.ledger.position("shadow:" + research))
        self.ledger.save_review(plan["alert_id"], T, {"verdict": "VETO", "note": "结构不干净"})
        self.assertEqual(self.ledger.counts()["ai_reviews"], 1)
        self.assertEqual(self.ledger.counts()["promotions"], 0)

    def test_daemon_fill_uses_the_same_ledger(self):
        from offline_daemon import daemon as m
        os.makedirs(m.LIBRARY_DIR, exist_ok=True)
        path = os.path.join(m.LIBRARY_DIR, "research.sqlite3")
        ledger = Ledger(path)
        plan = signal()
        try:
            ledger.record_candidate(plan)
            ledger.store.upsert_klines("BTCUSDT", "1m", [stop_bar()])
        finally:
            ledger.close()
        buy = fill("hook-buy", "BUY", T, 100.0, "hook-pos")
        sell = fill("hook-sell", "SELL", T + 60_000, 100.4, "hook-pos")
        self.assertTrue(m.apply_user_action({
            "eventId": "hook-buy", "recordType": "MANUAL_FILL", "alertId": plan["alert_id"], "actedAtMs": T, "fill": buy,
        })["ok"])
        self.assertTrue(m.apply_user_action({
            "eventId": "hook-sell", "recordType": "MANUAL_FILL", "alertId": plan["alert_id"], "actedAtMs": T + 60_000, "fill": sell,
        })["ok"])
        check = Ledger(path)
        try:
            paper = check.position("paper:hook-pos")
            system = check.position("system:hook-pos")
            label = check.label_for("system:hook-pos")
            self.assertEqual(paper["exit_price"], 100.4)
            self.assertEqual(system["exit_reason"], "STOP")
            self.assertEqual(label["barrier"], "STOP")
            self.assertAlmostEqual(label["net_pct"], -0.74)
        finally:
            check.close()

    def test_partial_fills_use_quantity_weighted_prices(self):
        self.ledger.record_buy(fill("w-buy-1", "BUY", T, 100.0, "pos-w"))
        second = fill("w-buy-2", "BUY", T + 1_000, 110.0, "pos-w")
        second["quantity"] = 0.03
        opened = self.ledger.record_buy(second)
        paper = self.ledger.position(opened["paperTwinId"])
        buy = (100 * 0.01 + 110 * 0.03) / 0.04
        self.assertAlmostEqual(paper["entry_price"], buy)
        self.assertEqual(paper["notional_usdt"], V2_PAPER_NOTIONAL_USDT)
        self.ledger.record_sell(fill("w-sell-1", "SELL", T + 2_000, 100.0, "pos-w"), inventory_closed=False)
        last = fill("w-sell-2", "SELL", T + 3_000, 120.0, "pos-w")
        last["quantity"] = 0.03
        closed = self.ledger.record_sell(last, inventory_closed=True)
        sell = (100 * 0.01 + 120 * 0.03) / 0.04
        self.assertAlmostEqual(closed["userNetPct"], round((sell * .04 - .001 - (buy * .04 + .001)) / (buy * .04 + .001) * 100, 4))
        self.assertEqual(self.ledger.position(opened["paperTwinId"])["notional_usdt"], V2_PAPER_NOTIONAL_USDT)

    def test_system_close_uses_cache_bars_when_klines_are_empty(self):
        plan = signal()
        self.ledger.record_candidate(plan)
        opened = self.ledger.record_buy(fill("c-buy", "BUY", T, 100.0, "pos-c"), signal_id=plan["alert_id"])
        closed = self.ledger.record_sell(
            fill("c-sell", "SELL", T + 60_000, 100.4, "pos-c"), bars_1m=[stop_bar()])
        self.assertEqual(closed["labelId"], "label:" + opened["systemTwinId"])
        self.assertEqual(self.ledger.position(opened["systemTwinId"])["state"], "CLOSED")
        self.assertEqual(self.ledger.position(opened["systemTwinId"])["exit_reason"], "STOP")


if __name__ == "__main__":
    unittest.main()
