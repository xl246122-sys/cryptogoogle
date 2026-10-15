import copy
import json
import time
import unittest
from unittest.mock import patch
from offline_daemon import daemon as m, ROOT

class SignalValidityTests(unittest.TestCase):
    def setUp(self):
        self.now = int(time.time() * 1000)
        def series(count, step, low=99.8, high=100.8):
            return [dict(time=self.now-(count-i)*step, close_time=self.now-(count-i-1)*step-1,
                         open=100.2 if i % 2 else 100.3, close=100.3 if i % 2 else 100.2,
                         high=high, low=low, volume=100., taker_buy_base=60., is_closed=True) for i in range(count)]
        self.micro = series(48, 60000, 100., 100.5)
        self.hourly = series(48, 3600000)
        self.regime = series(96, 900000)
        self.regime[-10]['high'] = 103.0  # Confirmed overhead resistance; do not invent an ATR target.
        self.hourly[-8]['high'] = 104.0
        self.five = series(48, 300000, 100., 100.6)
        self.five[-1].update(open=100.2, close=100.65, high=100.67, low=100., volume=200., taker_buy_base=120.)
        self.ticker = dict(symbol='BTCUSDT', price=100.65, change24h=0., high24h=100.8, low24h=99.8,
                           ask_price=100.65, timestamp=self.now)
        self.book = dict(is_valid=True, spread=.01, imbalance=.1, bid_vol=110., ask_vol=90.)
        self.macro = dict(trend='BULLISH', is_bearish=False, is_strongly_bearish=False, ma20=100., rsi=60.)

    def scan(self):
        return m.scan_symbol('BTCUSDT', self.ticker, self.macro, self.micro, self.book, self.hourly, self.regime, self.five)

    def test_real_positive_scan_and_wire_contract(self):
        sig = self.scan()
        self.assertIsNotNone(sig, 'Positive fixture must reach a real signal, never vacuously pass')
        self.assertEqual(sig['strategy'], 'BURST_BREAKOUT')
        self.assertEqual(sig['stop_loss'], 100.)
        self.assertTrue(m.entry_is_valid(sig, self.ticker))
        payload = m.fcm_payload(sig)
        self.assertEqual(float(payload['timestamp']), sig['timestamp'])
        self.assertEqual(float(payload['rsi14']), sig['rsi14'])
        self.assertLessEqual(sig['expires_at'] - sig['timestamp'], 90000)
        (ROOT / 'tests/signal_payload.fixture.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')

    def test_fallen_breakout_rejected(self):
        self.ticker['price'] = 100.4
        self.assertIsNone(self.scan())

    def test_weak_taker_cannot_use_alternate_breakout(self):
        self.five[-1]['taker_buy_base'] = 20.
        self.assertIsNone(m._closed_breakout(self.five, self.regime))
        self.assertIsNone(self.scan())

    def test_wick_failure_cannot_use_alternate_breakout(self):
        self.five[-1]['high'] = 102.
        self.assertIsNone(self.scan())

    def test_old_breakout_rejected(self):
        for candle in self.five: candle['close_time'] -= 120000
        self.assertIsNone(self.scan())

    def test_already_chased_above_confirmation_close_rejected(self):
        self.ticker['price'] = 101.
        self.assertIsNone(self.scan())

    def test_old_micro_rejected(self):
        for candle in self.micro: candle['close_time'] -= 86400000
        self.assertIsNone(self.scan())

    def test_entry_contract_limits(self):
        c = m.entry_contract(100, 101, 99.5, self.now - 1000, 99.9, self.now)
        self.assertIsNotNone(c)
        self.assertGreaterEqual(c['entry_min'], 99.9)
        self.assertLessEqual(c['entry_max'], 100.15)
        self.assertIsNone(m.entry_contract(100, 100.45, 99.8, self.now-1000, now_ms=self.now))
        self.assertIsNone(m.entry_contract(100, 101, 99.5, self.now-120000, now_ms=self.now))
        self.assertIsNone(m.entry_contract(100, 101, 99.5, self.now+1, now_ms=self.now))

    def test_recheck_rejects_expiry_price_and_unavailable_quote(self):
        sig = self.scan()
        self.assertIsNotNone(sig)
        self.assertFalse(m.entry_is_valid(sig, None))
        self.assertFalse(m.entry_is_valid(sig, self.ticker, sig['expires_at']))
        for update in ({'ask_price': 100.4}, {'ask_price': 105}, {'ask_price': float('nan')},
                       {'timestamp': self.now-11000}, {'symbol': 'SUIUSDT'}, {'ask_price': 0}):
            self.assertFalse(m.entry_is_valid(sig, {**self.ticker, **update}), update)

    def test_15m_breakout_uses_same_taker_and_wick_rules(self):
        self.regime[-1].update(open=100.2, close=100.85, high=100.87, volume=200., taker_buy_base=120.)
        self.assertEqual(m._closed_breakout([], self.regime)['label'], '15m')
        self.regime[-1]['taker_buy_base'] = 20.
        self.assertIsNone(m._closed_breakout([], self.regime))

    def test_fcm_ttl_and_expired_not_sent(self):
        from types import SimpleNamespace
        captured = []
        fake = SimpleNamespace(Message=lambda **kw: kw, Notification=lambda **kw: kw,
            AndroidConfig=lambda **kw: kw, AndroidNotification=lambda **kw: kw,
            send=lambda msg: captured.append(msg) or 'test')
        sig = self.scan()
        with patch.object(m, 'FCM_INITIALIZED', True), patch.object(m, 'messaging', fake, create=True):
            self.assertTrue(m.send_fcm_alert('test', 'test', m.fcm_payload(sig)))
            self.assertGreater(captured[0]['android']['ttl'].total_seconds(), 0)
            self.assertLessEqual(captured[0]['android']['ttl'].total_seconds(), 90)
            sig['expires_at'] = self.now-1
            self.assertFalse(m.send_fcm_alert('test', 'test', m.fcm_payload(sig)))
            self.assertEqual(len(captured), 1)

if __name__ == '__main__': unittest.main()
