import ast
import copy
import hashlib
import json
import pathlib
import tempfile
import unittest
import zipfile
from unittest.mock import patch
from offline_daemon import ROOT
from cryptog.market import MarketCache, INTERVALS
from cryptog.evaluation import evaluate
from cryptog.clock import at_time
from cryptog.storage import EventStore
from cryptog.security import DeviceAuth, tls_context
from cryptog.notifications import NotificationWorker
import threading

NOW = 1791988800100

def fixture():
    cache = MarketCache()
    cache.sync_clock(NOW,NOW,NOW)
    series = {}
    for interval,step in INTERVALS.items():
        end = NOW//step*step
        series[interval] = [[end-(96-i)*step,100.2,100.8,100.,100.3,100.,end-(95-i)*step-1,0,0,60.] for i in range(96)]
    cache.seed(series,{'lastUpdateId':100,'bids':[['100.29','110']],'asks':[['100.30','90']]},NOW)
    cache.ingest({'e':'depthUpdate','s':'BTCUSDT','E':NOW,'U':100,'u':101,'b':[],'a':[]},NOW)
    cache.ingest({'e':'24hrTicker','s':'BTCUSDT','E':NOW,'c':'100.3','P':'0','h':'100.8','l':'100'},NOW)
    cache.ingest({'e':'aggTrade','s':'BTCUSDT','E':NOW,'T':NOW,'a':1,'p':'100.3','q':'1','m':False},NOW)
    return cache

class StageOneTests(unittest.TestCase):
    def test_hourly_bollinger_closed_population_variance(self):
        from cryptog.market_state import diagnose_macro_trend
        import math
        candles = [{"close": 100+i, "high": 101+i, "low": 99+i, "open": 100+i,
                    "volume": 10, "close_time": NOW-(20-i)*3600000, "is_closed": True} for i in range(20)]
        ticker = {"price": 119, "change24h": 0}
        with at_time(NOW):
            bands = diagnose_macro_trend(candles, ticker)["bollinger"]
            self.assertAlmostEqual(bands["upper"], 109.5+2*math.sqrt(33.25))
            self.assertAlmostEqual(bands["lower"], 109.5-2*math.sqrt(33.25))
            forming = dict(candles[-1], close=99999, close_time=NOW+3600000, is_closed=False)
            self.assertEqual(diagnose_macro_trend(candles+[forming], ticker)["bollinger"], bands)
            self.assertIsNone(diagnose_macro_trend(candles[:19], ticker)["bollinger"])

    def test_depth_bridge_duplicate_and_gap(self):
        c=fixture(); self.assertTrue(c.snapshot(NOW)['healthy'])
        duplicate={'e':'depthUpdate','s':'BTCUSDT','E':NOW,'U':99,'u':101,'b':[['100.29','0']],'a':[]}
        self.assertFalse(c.ingest(duplicate,NOW)); self.assertIn(100.29,c.bids)
        with self.assertRaises(ValueError): c.ingest(dict(duplicate,U=103,u=104),NOW)
        self.assertFalse(c.snapshot(NOW)['healthy'])

    def test_depth_absolute_quantity_delete_and_cross(self):
        c=fixture()
        d={'e':'depthUpdate','s':'BTCUSDT','E':NOW+1,'U':102,'u':102,'b':[['100.29','50'],['100.28','5']],'a':[]}
        c.ingest(d,NOW+1); self.assertEqual(c.bids[100.29],50)
        c.ingest(dict(d,U=103,u=103,b=[['100.28','0']]),NOW+1); self.assertNotIn(100.28,c.bids)
        with self.assertRaises(ValueError): c.ingest(dict(d,U=104,u=104,b=[['101','1']]),NOW+1)

    def test_disconnect_stale_clock_and_candle_gap_block(self):
        c=fixture(); c.disconnect('OFFLINE'); self.assertFalse(c.snapshot(NOW)['healthy'])
        c=fixture(); self.assertFalse(c.snapshot(NOW+11000)['healthy'])
        c=fixture(); c.sync_clock(NOW+6000,NOW,NOW); self.assertIn('CLOCK_UNCERTAIN',c.snapshot(NOW)['issues'])
        c=fixture(); del c.bars['5m'][sorted(c.bars['5m'])[-2]]
        self.assertIn('BAR_GAP:5m',c.snapshot(NOW)['issues'])

    def test_aggregate_trade_duplicates_and_gap(self):
        c=fixture(); d={'e':'aggTrade','s':'BTCUSDT','E':NOW,'T':NOW,'a':1,'p':'100','q':'2','m':True}
        self.assertFalse(c.ingest(d,NOW))
        with self.assertRaises(ValueError): c.ingest(dict(d,a=3),NOW)

    def test_snapshot_excludes_forming_and_rejects_future_closed(self):
        c=fixture(); start=NOW//60000*60000
        payload={'e':'kline','s':'BTCUSDT','E':NOW,'k':{'i':'1m','t':start,'T':start+59999,'o':'100','h':'101','l':'99','c':'100','v':'1','V':'.6','x':False}}
        c.ingest(payload,NOW)
        self.assertTrue(all(b['close_time']<NOW for b in c.snapshot(NOW)['series']['1m']))
        payload['E']=NOW+1; payload['k']['x']=True
        with self.assertRaises(ValueError): c.ingest(payload,NOW+1)

    def test_replay_same_input_same_result_without_mutation(self):
        s=fixture().snapshot(NOW); original=copy.deepcopy(s)
        a=evaluate(s); b=evaluate(s)
        self.assertEqual(a,b); self.assertEqual(s,original)
        self.assertEqual(a['ruleVersion'],'three-models-v1')
        self.assertNotIn('tp1',a['volatility'])

    def test_future_bar_and_nonfinite_rejected_even_in_healthy_input(self):
        s=fixture().snapshot(NOW); s['series']['5m'][-1]['close_time']=NOW+1
        self.assertEqual(evaluate(s)['status'],'BLOCK_ENTRY')
        s=fixture().snapshot(NOW); s['series']['1m'][-1]['close']=float('nan')
        self.assertEqual(evaluate(s)['status'],'BLOCK_ENTRY')

    def test_clock_context_does_not_leak(self):
        from cryptog.clock import clock
        with at_time(NOW): self.assertEqual(clock.time(),NOW/1000)
        self.assertNotEqual(clock.time(),NOW/1000)

    def test_frozen_v112_strategy_parity(self):
        from cryptog import strategy
        from cryptog.config import TRADE_POLICIES
        raw=(ROOT/'tests/fixtures/v112_rules.py').read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(),(ROOT/'tests/fixtures/v112_rules.sha256').read_text().strip())
        tree=ast.parse(raw.decode())
        # Only definitions and literal constants, never original storage/FCM initialization.
        ns={'math':__import__('math'),'time':type('T',(),{'time':staticmethod(lambda:NOW/1000)})(),
            'List':list,'Optional':__import__('typing').Optional,'Tuple':tuple,'Dict':dict,'log_skip':lambda _:None}
        from cryptog import config
        ns.update({k:v for k,v in vars(config).items() if k.isupper()})
        frozen_config=json.loads((ROOT/'tests/fixtures/v112_config.json').read_text())
        for key,value in frozen_config.items(): self.assertEqual(getattr(config,key),value)
        ns.update(frozen_config)
        names={'TechnicalIndicators','get_closed_candles','validate_market_data_quality','verify_micro_range_reversal',
               'diagnose_cascade_downtrend','_closed_breakout','entry_contract','observed_resistances','stable_range_box',
               'recent_crash_confirmed','model_targets','scan_symbol'}
        defs=ast.Module(body=[n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.ClassDef)) and n.name in names],type_ignores=[])
        exec(compile(defs,'frozen-v112','exec'),ns)
        s=fixture().snapshot(NOW); bars=s['series']; ticker=s['ticker']
        macro={'trend':'BULLISH','is_bearish':False,'is_strongly_bearish':False,'ma20':100.,'rsi':60.}
        bars['5m'][-1].update(open=100.2,close=100.85,high=100.87,low=100.,volume=200.,taker_buy_base=120.)
        bars['15m'][-10]['high']=103.;bars['1h'][-8]['high']=104.
        accepted=0
        with at_time(NOW):
            for price in (100.85,100.84,100.9,100.2,101.5):
                for taker in (120.,40.):
                    ticker['price']=price;bars['5m'][-1]['taker_buy_base']=taker
                    args=('BTCUSDT',ticker,macro,bars['1m'],s['book'],bars['1h'],bars['15m'],bars['5m'])
                    before=ns['scan_symbol'](*copy.deepcopy(args));after=strategy.scan_symbol(*copy.deepcopy(args))
                    self.assertEqual(before,after)
                    accepted+=int(after is not None)
        self.assertGreater(accepted,0,'Parity cannot pass solely by rejecting every fixture')
        self.assertEqual(TRADE_POLICIES['RANGE']['min_net_tp1'],1.)

    def test_journal_conflict_replay_and_restart(self):
        path=pathlib.Path(tempfile.mkdtemp())/'events.db'
        s=EventStore(path); snap=fixture().snapshot(NOW)
        s.record_evaluation(snap,evaluate(snap));s.close()
        s=EventStore(path); self.assertEqual(len(s.evaluations()),1)
        s.append('a',NOW,'TEST',{'v':1})
        with self.assertRaises(ValueError): s.append('a',NOW,'TEST',{'v':2})
        s.close()

    def test_outbox_lease_restart_and_no_ttl_refresh(self):
        path=pathlib.Path(tempfile.mkdtemp())/'events.db'; s=EventStore(path)
        s.enqueue('a',{'expires_at':NOW+90000});s.enqueue('a',{'expires_at':NOW+900000})
        self.assertEqual(s.claim(NOW)[0],'a'); self.assertIsNone(s.claim(NOW+1));s.close()
        s=EventStore(path); self.assertEqual(s.claim(NOW+30001)[0],'a')
        s.finish('a',NOW+30001,'SENT');self.assertIsNone(s.claim(NOW+40000))
        s.enqueue('b',{'expires_at':NOW+1000});self.assertIsNone(s.claim(NOW+1001))
        self.assertEqual(s.health()['EXPIRED'],1);s.close()

    def test_shadow_worker_never_sends_and_invalid_entry_never_sends(self):
        s=EventStore(':memory:'); c=fixture();s.enqueue('a',{'expires_at':NOW+90000})
        sent=[];w=NotificationWorker(s,c,threading.Event(),lambda *args:sent.append(args))
        w.step(NOW);self.assertEqual(s.health(),{'PENDING':1});self.assertEqual(sent,[])
        w.enabled=True;w.step(NOW);self.assertEqual(sent,[]);self.assertEqual(s.health(),{'INVALIDATED':1})
        s.close()

    def test_device_auth_revocation_permissions_rate_limit(self):
        path=pathlib.Path(tempfile.mkdtemp())/'devices.json';token='test_'+'a'*40
        path.write_text(json.dumps({'phone':{'sha256':hashlib.sha256(token.encode()).hexdigest(),'write':False}}))
        auth=DeviceAuth(path)
        self.assertTrue(auth.allow(token,'ip'));self.assertFalse(auth.allow(token,'ip',True));self.assertFalse(auth.allow('x'*40,'ip'))
        for _ in range(125): auth.allow(token,'ip')
        self.assertFalse(auth.allow(token,'ip'))
        path.write_text('{}');self.assertFalse(auth.allow(token,'other-ip'))

    def test_plaintext_start_is_rejected(self):
        with patch.dict('os.environ',{},clear=True):
            with self.assertRaises(RuntimeError): tls_context()

    def test_expired_forming_bar_is_not_implicitly_promoted(self):
        c=fixture();start=NOW//60000*60000
        c.bars['1m'][start]=dict(time=start,close_time=start+59999,open=100.,high=101.,low=99.,close=100.,volume=1.,taker_buy_base=.6,is_closed=False)
        s=c.snapshot(start+61000)
        self.assertNotIn(start,[b['time'] for b in s['series']['1m']])

    def test_legacy_backup_preserves_torn_bytes_before_recovery(self):
        from cryptog.migration import backup_legacy
        directory=pathlib.Path(tempfile.mkdtemp());original=b'{"event":1}\n{"partial"'
        (directory/'actions.jsonl').write_bytes(original)
        backup=backup_legacy(directory)
        self.assertEqual((backup/'actions.jsonl').read_bytes(),original)
        self.assertEqual((directory/'actions.jsonl').read_bytes(),original)
        self.assertEqual(json.loads((backup/'manifest.json').read_text())['actions.jsonl'],hashlib.sha256(original).hexdigest())

    def test_notification_failure_retries_success_persists_cooldown(self):
        s=EventStore(':memory:');c=fixture();sent=[]
        sig={'timestamp':NOW,'expires_at':NOW+90000,'entry_min':100.2,'entry_max':100.4,'stop_loss':100.,'target_tp1':102.}
        s.enqueue('a',sig)
        def send(*args): sent.append(args);return len(sent)>1
        w=NotificationWorker(s,c,threading.Event(),send,enabled=True)
        w.step(NOW);self.assertEqual(s.health(),{'PENDING':1})
        w.step(NOW+5000);self.assertEqual(s.health(),{'SENT':1})
        s.enqueue('b',dict(sig,expires_at=NOW+95000));self.assertIsNone(s.claim(NOW+6000,90000))
        self.assertEqual(len(sent),2);s.close()

    def test_opportunity_terminal_state_survives_retry_and_disconnected_expiry(self):
        s=EventStore(':memory:')
        sig={'timestamp':NOW,'expires_at':NOW+1000,'entry_min':100.2,'entry_max':100.4,'stop_loss':100.,'target_tp1':102.}
        self.assertEqual(s.opportunity('a',sig),'BUY_CANDIDATE')
        s.advance_opportunities(NOW+1000,None)
        self.assertEqual(s.opportunity('a',dict(sig,expires_at=NOW+90000)),'EXPIRED')
        s.opportunity('b',dict(sig,expires_at=NOW+90000));s.enqueue('b',dict(sig,expires_at=NOW+90000))
        s.advance_opportunities(NOW+1,dict(symbol='BTCUSDT',ask_price=101.,timestamp=NOW+1))
        self.assertEqual(s.opportunity('b',sig),'INVALIDATED')
        self.assertEqual(s.health(),{'INVALIDATED':1});s.close()

    def test_evaluation_window_does_not_grow_with_websocket_cache(self):
        from cryptog import evaluation
        snapshot=fixture().snapshot(NOW)
        original=evaluation.scan_symbol
        lengths=[]
        def inspect(*args):
            lengths.append([len(args[i]) for i in (3,5,6,7)])
            return original(*args)
        with patch.object(evaluation,'scan_symbol',side_effect=inspect):
            evaluate(snapshot)
        self.assertEqual(lengths,[[47,47,95,47]])

if __name__=='__main__': unittest.main()
