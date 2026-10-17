import unittest

from cryptog.kline_store import ResearchStore


class KlineStoreTests(unittest.TestCase):
    def test_round_trip_and_confirmation(self):
        store = ResearchStore(":memory:")
        try:
            bar = {"time": 1_000, "open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 3,
                   "close_time": 1_999, "taker_buy_base": 1}
            self.assertEqual(store.upsert_klines("BTCUSDT", "15m", [bar, bar]), 2)
            self.assertEqual(store.klines("BTCUSDT", "15m")[0]["close"], 1.5)
            self.assertEqual(store.coverage()["15m"]["count"], 1)
            store.upsert_open_interest("BTCUSDT", [{"time": 0, "oi": 100}, {"time": 3_600_000, "oi": 96}])
            store.upsert_funding("BTCUSDT", [{"time": 0, "rate": -0.0002}])
            store.upsert_taker("BTCUSDT", [{"time": 3_600_000, "sell_buy_ratio": 1.8}])
            view = store.confirmation("BTCUSDT", 3_600_000)
        finally:
            store.close()
        self.assertEqual(view["status"], "ok")
        self.assertAlmostEqual(view["oi_change_1h_pct"], -4.0)
        self.assertEqual(view["funding_rate"], -0.0002)
        self.assertEqual(view["taker_sell_ratio"], 1.8)


if __name__ == "__main__":
    unittest.main()
