import json
import pathlib
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scratch'))

from cryptog.storage import EventStore
from cryptog.ai_engine import AIEngine, AIAnalystWorker, build_ai_prompt

NOW = 1792000000000

def make_snapshot(price=67000.0, drop_recent=False):
    series = {}
    for tf, count in [('1m', 30), ('5m', 24), ('15m', 16), ('1h', 12)]:
        bars = []
        for i in range(count):
            t = NOW - (count - i) * 60000
            p = price
            if drop_recent and tf == '1m' and i >= count - 3:
                # 1.5% drop in last 3 minutes
                p = price * (1 - (i - count + 4) * 0.006)
            bars.append({
                'time': t,
                'close_time': t + 59999,
                'open': p,
                'high': p + 20,
                'low': p - 20,
                'close': p,
                'volume': 15.0,
                'taker_buy_base': 9.0,
                'is_closed': True
            })
        series[tf] = bars

    return {
        'atMs': NOW,
        'healthy': True,
        'ticker': {
            'bid_price': price,
            'ask_price': price + 5.0, # spread ~0.007%
            'change24h': -1.5,
            'high24h': price + 1000,
            'low24h': price - 1000,
        },
        'book': {
            'bids': [[str(price - i * 5), '10'] for i in range(10)],
            'asks': [[str(price + 5 + i * 5), '8'] for i in range(10)],
        },
        'series': series
    }

class MockCache:
    def __init__(self, snapshot):
        self.snap = snapshot
    def snapshot(self, now_ms):
        return self.snap

class AIEngineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db_path = str(pathlib.Path(self.tmp) / 'events.sqlite3')
        self.store = EventStore(self.db_path)
        self.snapshot = make_snapshot()
        self.cache = MockCache(self.snapshot)
        self.fcm_calls = []
        self.stop = threading.Event()
        self.ai = AIEngine(self.store, self.cache, lambda title, body, extra: (self.fcm_calls.append((title, body, extra)) or True), self.stop)

    def tearDown(self):
        self.stop.set()
        self.store.close()

    def test_prompt_builder(self):
        prompt = build_ai_prompt(self.snapshot)
        self.assertIn('BTC/USDT', prompt)
        self.assertIn('67000.00', prompt)
        self.assertIn('5分钟核心K线序列', prompt)
        self.assertIn('独立量化决策', prompt)

    def test_config_crud_and_security_masking(self):
        cfg = self.ai.get_config()
        self.assertEqual(cfg['provider'], 'GEMINI')
        self.assertEqual(cfg['intervalSeconds'], 300)

        # Update config with API key
        self.ai.set_config({'apiKey': 'AIzaSySecret123456789', 'provider': 'DEEPSEEK', 'model': 'deepseek-chat'})
        new_cfg = self.ai.get_config()
        self.assertEqual(new_cfg['apiKey'], 'AIzaSySecret123456789')
        self.assertEqual(new_cfg['provider'], 'DEEPSEEK')

        # Status output must mask the key
        status = self.ai.status()
        self.assertTrue(status['hasApiKey'])
        self.assertEqual(status['config']['apiKey'], 'AIza****6789')

    def test_pre_dispatch_verification_price_escaped(self):
        decision = {
            'is_buy': True,
            'confidence': 85,
            'scenario': 'FLASH_DROP_REBOUND',
            'scenario_name_zh': '暴跌急挫企稳反弹',
            'entry_min': 66900.0,
            'entry_max': 66950.0, # Ask is 67005, which is already above max entry
            'target_tp1': 68000.0,
            'stop_loss': 66500.0,
            'summary_zh': '测试急跌反弹'
        }
        eval_record = {'provider': 'GEMINI', 'model': 'gemini-2.5-flash'}
        # Price escaped above entry_max: must block!
        pushed = self.ai.verify_and_push_signal(eval_record, decision, NOW)
        self.assertFalse(pushed)
        self.assertEqual(len(self.fcm_calls), 0)

    def test_pre_dispatch_verification_valid_and_push(self):
        decision = {
            'is_buy': True,
            'confidence': 90,
            'scenario': 'RANGE_SUPPORT_BOUNCE',
            'scenario_name_zh': '区间下沿支撑反弹',
            'entry_min': 66950.0,
            'entry_max': 67100.0, # Ask is 67005.0, cleanly inside [66950, 67100]
            'target_tp1': 68200.0, # Net gain > 1.5%
            'stop_loss': 66300.0,  # Module risk ~1%
            'profit_pct1': 1.67,
            'summary_zh': '测试区间下沿支撑企稳',
            'hold_minutes':60,'anchor_timeframe':'5m','anchor_time_ms':self.snapshot['series']['5m'][-1]['time']
        }
        eval_record = {'provider': 'GEMINI', 'model': 'gemini-2.5-flash'}
        pushed = self.ai.verify_and_push_signal(eval_record, decision, NOW)
        self.assertTrue(pushed)
        self.assertEqual(len(self.fcm_calls), 0)
        with patch('cryptog.ai_engine.time.time', return_value=NOW/1000):
            self.ai.dispatch_pending()
        self.assertEqual(len(self.fcm_calls), 1)
        title, body, extra = self.fcm_calls[0]
        self.assertIn('Crypto-G AI买入预警', title)
        self.assertIn('区间震荡', title)
        self.assertIn('$66950.00~$67100.00', body)
        self.assertEqual(extra['eventType'], 'AI_BUY_ALERT')

        # Check SQLite storage
        with self.store.lock, self.store.db:
            sig_row = self.store.db.execute("SELECT scenario, state FROM ai_signals").fetchone()
            self.assertEqual(sig_row[0], 'RANGE_SUPPORT_BOUNCE')
            self.assertEqual(sig_row[1], 'FCM_ACCEPTED')

            # Check inbox queue insertion
            q_row = self.store.db.execute("SELECT payload FROM observation_queue WHERE payload LIKE '%AI_BUY_ALERT%'").fetchone()
            self.assertIsNotNone(q_row)

    def test_execute_analysis_mocked_llm(self):
        self.ai.set_config({'apiKey': 'test_mock_key', 'provider': 'GEMINI'})
        mock_res = {
            'is_buy': False,
            'confidence': 50,
            'scenario': 'NONE',
            'scenario_name_zh': '观望无机会',
            'summary_zh': '大盘处于震荡中间位置，无明确支撑或突破'
        }
        with patch.object(self.ai, 'call_gemini', return_value=mock_res):
            res = self.ai.execute_analysis(trigger_reason='SCHEDULED_5M')
            self.assertTrue(res['ok'])
            self.assertFalse(res['evaluation']['isBuy'])
            self.assertEqual(res['evaluation']['scenario'], 'NONE')

        with self.store.lock, self.store.db:
            eval_row = self.store.db.execute("SELECT trigger_reason, is_buy FROM ai_evaluations").fetchone()
            self.assertEqual(eval_row[0], 'SCHEDULED_5M')
            self.assertEqual(eval_row[1], 0)

    def test_event_shock_detection(self):
        worker = AIAnalystWorker(self.ai, self.stop)
        # Normal market: no shock
        self.assertIsNone(worker.detect_event_shock(self.snapshot))

        # Sudden drop snapshot (1.5% in 3m)
        shock_snap = make_snapshot(drop_recent=True)
        detected = worker.detect_event_shock(shock_snap)
        self.assertIsNotNone(detected)
        self.assertIn('EVENT_FLASH_DROP', detected)

class AuditRegressionTests(AIEngineTests):
    def test_config_switches_and_invalid_values(self):
        self.ai.set_config({'enabled5m': False, 'enabledEventTrigger': False})
        self.assertFalse(self.ai.get_config()['enabled5m'])
        self.assertFalse(self.ai.get_config()['enabledEventTrigger'])
        with self.assertRaises(ValueError):
            self.ai.set_config({'intervalSeconds': 0})
        with self.assertRaises(ValueError):
            self.ai.set_config({'enabled': 'false'})

    def test_real_aggregated_book_prompt(self):
        self.snapshot['book'] = {'imbalance': 0.321, 'bid_vol': 20, 'ask_vol': 10}
        self.assertIn('+0.321', build_ai_prompt(self.snapshot))

    def test_rejected_buy_contract_and_history(self):
        self.ai.set_config({'apiKey': 'mock'})
        decision = {'is_buy': True, 'entry_min': 66900, 'entry_max': 66950,
                    'target_tp1': 68200, 'stop_loss': 66600, 'scenario': 'TEST'}
        with patch.object(self.ai, 'call_gemini', return_value=decision):
            result = self.ai.execute_analysis()
        self.assertFalse(result['evaluation']['isBuy'])
        state = self.ai.status()
        self.assertEqual(state['buyCount'], 0)
        self.assertFalse(state['recentEvaluations'][0]['isBuy'])
        self.assertIn('atMs', state['recentEvaluations'][0])

    def test_string_boolean_rejected(self):
        self.ai.set_config({'apiKey': 'mock'})
        with patch.object(self.ai, 'call_gemini', return_value={'is_buy': 'false'}):
            self.assertFalse(self.ai.execute_analysis()['ok'])

class DeliveryRecoveryTests(AIEngineTests):
    def test_restart_restores_deduplication(self):
        decision = {'entry_min':66950,'entry_max':67100,'target_tp1':68200,'stop_loss':66300,'scenario':'RANGE_SUPPORT_BOUNCE','summary_zh':'支撑收复','hold_minutes':60,'anchor_timeframe':'5m','anchor_time_ms':self.snapshot['series']['5m'][-1]['time']}
        meta = {'provider':'GEMINI','model':'mock'}
        self.assertTrue(self.ai.verify_and_push_signal(meta,decision,NOW))
        restored = AIEngine(self.store,self.cache,self.ai.send_fcm_alert,self.stop)
        self.assertFalse(restored.verify_and_push_signal(meta,decision,NOW+1000))
        with patch('cryptog.ai_engine.time.time',return_value=(NOW+91000)/1000):
            restored.dispatch_pending()
        self.assertEqual(self.fcm_calls,[])
        self.assertEqual(self.store.db.execute('SELECT state FROM ai_signals').fetchone()[0],'EXPIRED')

    def test_retry_revalidates_quote(self):
        decision = {'entry_min':66950,'entry_max':67100,'target_tp1':68200,'stop_loss':66300,'scenario':'RANGE_SUPPORT_BOUNCE','summary_zh':'支撑收复','hold_minutes':60,'anchor_timeframe':'5m','anchor_time_ms':self.snapshot['series']['5m'][-1]['time']}
        self.ai.verify_and_push_signal({'provider':'GEMINI','model':'mock'},decision,NOW)
        self.cache.snap['ticker']['ask_price']=67500
        with patch('cryptog.ai_engine.time.time',return_value=NOW/1000):
            self.ai.dispatch_pending()
        self.assertEqual(self.fcm_calls,[])
        self.assertEqual(self.store.db.execute('SELECT state FROM ai_signals').fetchone()[0],'INVALIDATED')

class CredentialTests(AIEngineTests):
    def test_provider_isolation_encryption_and_reset(self):
        self.ai.set_config({'provider':'GEMINI','apiKey':'gemini-secret'})
        self.ai.retry_at=9999999999999
        self.ai.last_error='old failure'
        self.ai.set_config({'provider':'DEEPSEEK','apiKey':'deepseek-secret'})
        self.assertEqual(self.ai.retry_at,0)
        self.assertIsNone(self.ai.last_error)
        raw=self.store.db.execute('SELECT payload FROM ai_config WHERE id=1').fetchone()[0]
        self.assertNotIn('deepseek-secret',raw)
        raw=self.store.db.execute('SELECT secret FROM ai_credentials WHERE provider=?',('DEEPSEEK',)).fetchone()[0]
        self.assertNotIn('deepseek-secret',raw)
        self.ai.set_config({'provider':'GEMINI'})
        self.assertEqual(self.ai.get_config()['apiKey'],'gemini-secret')
        restored=AIEngine(self.store,self.cache,self.ai.send_fcm_alert,self.stop)
        self.assertEqual(restored.get_config()['apiKey'],'gemini-secret')
        self.ai.set_config({'deleteKey':True})
        self.assertEqual(self.ai.get_config()['apiKey'],'')

    def test_busy_save_preserves_old_config(self):
        self.ai.lock.acquire()
        try:
            with self.assertRaises(ValueError): self.ai.set_config({'apiKey':'new'})
        finally: self.ai.lock.release()

    def test_verification_is_separate_from_analysis(self):
        self.ai.set_config({'apiKey':'test-key'})
        with patch.object(self.ai,'call_gemini',return_value={'is_buy':False}):
            self.assertTrue(self.ai.verify_connection()['ok'])
        self.assertEqual(self.ai.get_config()['connectionStatus'],'VERIFIED')
        self.assertEqual(self.ai.status()['evalCount'],0)

if __name__ == '__main__':
    unittest.main()
