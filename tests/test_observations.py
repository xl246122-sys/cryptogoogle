import json
import pathlib
import tempfile
import threading
import unittest
from cryptog.storage import EventStore
from cryptog.observations import ObservationWorker

NOW = 1792000000000

def make_bars(count=30, base=100.0, trend=0.0):
    bars = []
    for i in range(count):
        t = NOW - (count - i) * 60000
        p = base + i * trend
        bars.append({
            'time': t,
            'close_time': t + 59999,
            'open': p,
            'high': p + 0.5,
            'low': p - 0.5,
            'close': p,
            'volume': 10.0,
            'taker_buy_base': 6.0,
            'is_closed': True
        })
    return bars

class ObservationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db_path = str(pathlib.Path(self.tmp) / 'events.sqlite3')
        self.store = EventStore(self.db_path)
        self.sent = []
        self.stop = threading.Event()
        self.worker = ObservationWorker(self.store, self.stop, lambda title, body, extra: (self.sent.append((title, body, extra)) or True))

    def tearDown(self):
        self.stop.set()
        self.store.close()

    def test_hourly_summary_generation(self):
        bars = make_bars()
        s = {'atMs': NOW, 'healthy': True, 'series': {'1m': bars}, 'ticker': {'bid_price': 100.0}}
        d = {'macro': {'trend': 'NEUTRAL'}, 'reasons': ['未达入场要求'], 'research': []}

        # Initial tick sets the baseline hour
        self.worker.update(s, d)
        # Advance by 1 hour to trigger hourly summary
        s_next_hour = dict(s, atMs=NOW + 3600000)
        self.worker.update(s_next_hour, d)

        with self.store.lock, self.store.db:
            rows = self.store.db.execute("SELECT payload FROM observation_queue").fetchall()
        self.assertEqual(len(rows), 1)
        payload = json.loads(rows[0][0])
        self.assertEqual(payload['title'], 'Crypto-G 每小时扫描摘要')
        self.assertIn('暂无合格入场', payload['body'])

    def test_shock_observation_and_bound_variant_checks(self):
        # Create a 10m drop >= 1%
        bars = make_bars(count=30, base=100.0)
        # Drop the last 10 bars by 2%
        for i, b in enumerate(bars[-10:]):
            p = 100.0 - (i + 1) * 0.25 # up to 2.5% drop
            b.update(open=p + 0.1, high=p + 0.1, low=p - 0.1, close=p)

        s = {'atMs': NOW + 3600000, 'healthy': True, 'series': {'1m': bars}, 'ticker': {'bid_price': 97.5}}
        # Provide research checks for MINUTE_SHOCK_10 and OVERSOLD_RECOVERY with distinct check names
        oversold_checks = [{'name': 'RSI超卖要求', 'passed': False, 'detail': 'RSI未达到'}]
        shock_checks = [{'name': '分钟冲击跌幅', 'passed': True, 'detail': '跌幅达标'},
                        {'name': '主动买量改善', 'passed': False, 'detail': '买量未放大'}]

        d = {
            'macro': {'trend': 'BEARISH'},
            'research': [
                {'variant': 'OVERSOLD_RECOVERY', 'checks': oversold_checks},
                {'variant': 'MINUTE_SHOCK_10', 'checks': shock_checks}
            ]
        }

        # First update triggers 机会观察 with bound variant MINUTE_SHOCK_10
        self.worker.update(s, d)
        with self.store.lock, self.store.db:
            rows = self.store.db.execute("SELECT payload FROM observation_queue ORDER BY rowid").fetchall()
        # Hour summary + 机会观察
        titles = [json.loads(r[0])['title'] for r in rows]
        self.assertIn('Crypto-G 机会观察', titles)
        bodies = [json.loads(r[0])['body'] for r in rows]
        self.assertTrue(any('急跌' in b for b in bodies))

        # Check state has active observation bound to MINUTE_SHOCK_10
        with self.store.lock, self.store.db:
            state_row = self.store.db.execute("SELECT payload FROM observation_state WHERE id='current'").fetchone()
            state = json.loads(state_row[0])
            self.assertEqual(state['active']['variant'], 'MINUTE_SHOCK_10')

        # Now simulate price recovery: last candle close exceeds high of previous 3 candles
        recovered_bars = list(bars)
        last_high = max(c['high'] for c in recovered_bars[-4:-1])
        recovered_bars[-1] = dict(recovered_bars[-1], close=last_high + 0.5, high=last_high + 0.6)
        s_rec = {'atMs': NOW + 3600000 + 60000, 'healthy': True, 'series': {'1m': recovered_bars}, 'ticker': {'bid_price': last_high + 0.5}}

        self.worker.update(s_rec, d)

        with self.store.lock, self.store.db:
            rows = self.store.db.execute("SELECT payload FROM observation_queue ORDER BY rowid").fetchall()
        approach_notice = next((json.loads(r[0]) for r in rows if json.loads(r[0])['title'] == 'Crypto-G 条件接近'), None)
        self.assertIsNotNone(approach_notice)
        # CRITICAL TEST: The needed check must come from MINUTE_SHOCK_10 ('主动买量改善'), NOT OVERSOLD_RECOVERY ('RSI超卖要求')!
        self.assertIn('主动买量改善', approach_notice['body'])
        self.assertNotIn('RSI超卖要求', approach_notice['body'])

    def test_invalidation_when_breaking_support(self):
        bars = make_bars(count=30, base=100.0)
        for i, b in enumerate(bars[-10:]):
            p = 100.0 - (i + 1) * 0.25
            b.update(open=p, high=p, low=p, close=p)
        low_val = min(c['low'] for c in bars[-10:])
        s = {'atMs': NOW + 3600000, 'healthy': True, 'series': {'1m': bars}, 'ticker': {'bid_price': low_val}}
        d = {'macro': {'trend': 'BEARISH'}, 'research': []}
        self.worker.update(s, d)

        # Drop price below low * 0.999
        broken_s = {'atMs': NOW + 3600000 + 60000, 'healthy': True, 'series': {'1m': bars}, 'ticker': {'bid_price': low_val * 0.998}}
        self.worker.update(broken_s, d)

        with self.store.lock, self.store.db:
            rows = self.store.db.execute("SELECT payload FROM observation_queue ORDER BY rowid").fetchall()
        titles = [json.loads(r[0])['title'] for r in rows]
        self.assertIn('Crypto-G 机会失效', titles)

        # Active state should be cleared
        with self.store.lock, self.store.db:
            state = json.loads(self.store.db.execute("SELECT payload FROM observation_state WHERE id='current'").fetchone()[0])
            self.assertIsNone(state['active'])

    def test_observation_worker_health(self):
        self.worker.heartbeat = NOW
        h = self.worker.health(NOW + 2000)
        self.assertIn('healthy', h)
        self.assertIn('pending', h)
        self.assertIn('expired', h)
        self.assertIn('sent', h)
        self.assertIsNone(h['error'])

if __name__ == '__main__':
    unittest.main()
