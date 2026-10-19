"""Regression coverage for the October 18 audit; no network or notifications."""
import copy
import json
import tempfile
import threading
import unittest
import zlib
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace

from cryptog.context_feed import ContextFeed, STEPS, closed_history
from cryptog.engine_v2 import build_signal, context_issue, environment
from cryptog.notifications import NotificationWorker
from cryptog.storage import EventStore, canonical, decode_event

NOW = 1792328400000  # 2026-10-18 13:00 UTC


def signal():
    setup = dict(module='S1', entry_min=99.9, entry_max=100.1, entry_ref=100., stop=99.4,
                 invalidation=99.8, tp1=102., tp2_hint=103., anchor_time=NOW-900000,
                 trigger={'time': NOW-900000, 'close_time': NOW-1},
                 tp1_basis='test', reason='test', features={})
    env = dict(score=100, states=dict(d1='UP', h4='UP', h1='UP'), gates={}, label='test')
    return build_signal(setup, {'h1': {'rsi14': 50, 'atr14': 1}}, env, 100, NOW,
                        {'spread': .001}, {'oi_change_1h_pct': -4, 'funding_rate': -.0002, 'taker_sell_ratio': 2})


class AuditStageATests(unittest.TestCase):
    def test_capacity_forecast_warmup_warning_and_staleness(self):
        from cryptog.capacity import CapacityMonitor
        store = EventStore(':memory:')
        monitor = CapacityMonitor(store, '.')
        with patch('cryptog.capacity.shutil.disk_usage', return_value=SimpleNamespace(free=1000000, total=2000000)):
            monitor.sample(NOW)
            self.assertEqual(monitor.status(NOW)['state'], 'WARMUP')
            store.append('large', NOW, 'TEST', {'data': 'x'*100000})
            with self.assertLogs('cryptog.capacity', level='WARNING'):
                monitor.sample(NOW+60000)
            status = monitor.status(NOW+60000)
            self.assertGreater(status['journalGrowthBytesPerDay'], 0)
            self.assertLess(status['estimatedJournalDaysRemaining'], 7)
            self.assertEqual(status['state'], 'WARNING')
            self.assertEqual(monitor.status(NOW+200000)['state'], 'STALE')
        store.close()

    def test_all_context_frames_exclude_forming_and_reject_bad_history(self):
        def fetch(tf):
            step = STEPS[tf]
            boundary = NOW // step * step
            return [dict(time=t, close_time=t+step-1, open=100., high=101., low=99.,
                         close=100., volume=10., taker_buy_base=5.)
                    for t in range(boundary-300*step, boundary+step, step)]
        ctx = ContextFeed(threading.Event(), fetch=fetch).refresh(NOW)
        self.assertIsNone(context_issue(ctx, NOW))
        for tf in STEPS:
            bars = fetch(tf)
            self.assertEqual(len(closed_history(bars, tf, NOW)), 300)
            self.assertTrue(all(b['is_closed'] and b['close_time'] < NOW for b in closed_history(bars, tf, NOW)))
            for bad in (bars[:10]+bars[11:], bars[:-3], [dict(bars[0], close=float('nan'))]+bars[1:]):
                with self.assertRaises(ValueError):
                    closed_history(bad, tf, NOW)
        for tf in ('d1', 'h4', 'h1'):
            bad = copy.deepcopy(ctx)
            bad[tf]['close_time'] = NOW+1
            self.assertIsNotNone(context_issue(bad, NOW))

    def test_four_hour_gate_cannot_be_opened_by_live_price(self):
        frame = dict(close=98, ema25=100.5, ema99=100)
        ctx = {tf: dict(frame) for tf in ('d1', 'h4', 'h1')}
        for display in (False, True):
            env = environment(ctx, 101, NOW, live_display=display)
            self.assertFalse(env['gates']['S3'])
            self.assertFalse(env['gates']['S4'])
        ctx['h4']['close'] = ctx['h1']['close'] = 102
        self.assertTrue(environment(ctx, 98, NOW)['gates']['S3'])
        self.assertTrue(environment(ctx, 98, NOW)['gates']['S4'])

    def test_score_preserves_components_without_breaking_phone_range(self):
        made = signal()
        self.assertEqual(made['rule_score'], 100)
        self.assertEqual(made['raw_rule_score'], 124)
        self.assertEqual(made['friction_pct'], .24)

    def test_post_review_rechecks_price_expiry_health_and_breaker(self):
        for scenario in ('price', 'expiry', 'health', 'breaker', 'watch', 'valid'):
            with self.subTest(scenario=scenario):
                made = signal()
                made['tier'] = 'TRADE' if scenario == 'breaker' else 'WATCH'
                after = made['expires_at'] if scenario == 'expiry' else NOW+8000
                class Cache:
                    calls = 0
                    def snapshot(self, local):
                        self.calls += 1
                        at = NOW if self.calls == 1 else after
                        return dict(atMs=at, healthy=not (self.calls > 1 and scenario == 'health'),
                                    ticker=dict(ask_price=110 if self.calls > 1 and scenario == 'price' else 100,
                                                timestamp=at, symbol='BTCUSDT'))
                class Tracker:
                    def breaker(self, now): return {'pausedUntil': now+10000}
                with tempfile.TemporaryDirectory() as tmp:
                    store = EventStore(str(Path(tmp)/'journal.sqlite3'))
                    store.enqueue('test', made)
                    sent, cache = [], Cache()
                    worker = NotificationWorker(store, cache, threading.Event(), lambda *x: sent.append(x) or True,
                                                enabled=True, clock_ms=lambda: after)
                    worker._review = lambda *args: made
                    worker.tracker = Tracker()
                    worker.step(NOW)
                    self.assertEqual(cache.calls, 2)
                    expected = dict(price='INVALIDATED', expiry='EXPIRED', health='PENDING',
                                    breaker='CANCELLED', watch='SENT', valid='SENT')[scenario]
                    self.assertEqual(store.health(), {expected: 1})
                    self.assertEqual(bool(sent), expected == 'SENT')
                    store.close()

    def test_journal_lossless_reopen_legacy_and_missing_reference(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp)/'journal.sqlite3')
            store = EventStore(path)
            series = {'1m': [dict(time=i, close=100+i/17, volume=i*13.231) for i in range(1000)]}
            expected, old_bytes = [], 0
            for i in range(120):
                snap = dict(atMs=NOW+i*1000, ticker={'price': 100+i/123}, series=series, context={'close': 100})
                decision = {'status': 'WAIT', 'sequence': i}
                store.record_evaluation(snap, decision)
                expected.append({'input': snap, 'decision': decision})
                old_bytes += len(zlib.compress(canonical(expected[-1]).encode(), 3))
            store.record_evaluation(expected[-1]['input'], expected[-1]['decision'])
            actual_bytes = store.db.execute('SELECT sum(length(payload)) FROM events').fetchone()[0]
            actual_bytes += store.db.execute('SELECT sum(length(payload)) FROM evaluation_inputs').fetchone()[0]
            self.assertLess(actual_bytes, old_bytes*.15)
            self.assertEqual(store.db.execute('SELECT count(*) FROM evaluation_inputs').fetchone()[0], 2)
            store.close()
            store = EventStore(path)
            self.assertEqual(store.evaluations(), expected)
            raw = zlib.compress(json.dumps(expected[0]).encode())
            self.assertEqual(decode_event(raw), expected[0])
            store.db.execute('DELETE FROM evaluation_inputs')
            with self.assertRaisesRegex(ValueError, 'Missing evaluation input'):
                store.evaluations()
            store.close()


if __name__ == '__main__':
    unittest.main()
