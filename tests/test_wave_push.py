import json
from pathlib import Path
import sys
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scratch'))
from cryptog.wave_push import ResearchOutbox,payload_from_event,recheck,transport_fields

NOW=1792368060000
def source(group='B-R03',phase='DOWN_START',feature=NOW):
    return dict(eventId=f'{group}:5:{NOW-60000}',group=group,window=5,phase=phase,evidence={},
        plan=dict(entryLow=99.9,entryHigh=100.1,stop=99.6,target=101.2,minNet=.8,window=5,holdMinutes=30))
def quote(now=NOW):return dict(bid=99.99,ask=100,sourceMs=now-10,clockOffsetMs=0,observedMs=now,healthy=True)

class PushTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'push.db';self.o=ResearchOutbox(self.path)
    def tearDown(self):self.o.db.close();self.temp.cleanup()
    def test_explicit_observe_and_fcm_contract(self):
        for phase in ['DOWN_START','SELL_EXHAUSTION','REBOUND_CONFIRMED','INVALIDATED']:
            data,config=payload_from_event(source(phase=phase),NOW,NOW,NOW)
            checked=recheck(data,config,quote(),NOW)
            title,_,fields=transport_fields(checked)
            self.assertTrue(title.startswith('观察：【'))
            self.assertEqual(fields['signalType'],'OBSERVE');self.assertEqual(fields['tradeEligible'],'false')
            self.assertLess(data['revision'],2**53)
            self.assertNotIn('BUY',fields['signalType'])
    def test_warning_not_gated_by_profit_but_confirmation_is(self):
        p=source();p['plan']['target']=100.2
        d,c=payload_from_event(p,NOW,NOW,NOW);self.assertIsNone(recheck(d,c,quote(),NOW)['risk'])
        p['phase']='REBOUND_CONFIRMED';d,c=payload_from_event(p,NOW,NOW,NOW)
        with self.assertRaisesRegex(ValueError,'RISK_NET_SPACE'):recheck(d,c,quote(),NOW)
        d,c=payload_from_event(source(phase='REBOUND_CONFIRMED'),NOW,NOW,NOW)
        q=quote();q['ask']=100.5
        with self.assertRaisesRegex(ValueError,'RISK_ENTRY_RANGE'):recheck(d,c,q,NOW)
    def test_dedupe_restart_and_reverse_revision(self):
        d,c=payload_from_event(source('B-R00'),NOW,NOW,NOW);self.o.ingest(d,c,NOW)
        d2,c2=payload_from_event(source('B-R05'),NOW,NOW,NOW);self.o.ingest(d2,c2,NOW)
        self.assertEqual(self.o.db.execute('SELECT count(*) FROM deliveries').fetchone()[0],1)
        calls=[];self.o.step(quote(),NOW,lambda p:calls.append(p) or 'accepted')
        self.o.db.close();self.o=ResearchOutbox(self.path);self.o.step(quote(NOW+61000),NOW+61000,lambda p:calls.append(p))
        self.assertEqual(len(calls),1)
        d,c=payload_from_event(source('B-R03','SELL_EXHAUSTION'),NOW+1000,NOW+1000,NOW+1000);self.o.ingest(d,c,NOW+1000)
        d,c=payload_from_event(source('B-R03'),NOW,NOW,NOW);key=self.o.ingest(d,c,NOW)
        self.assertEqual(self.o.db.execute('SELECT state FROM deliveries WHERE id=?',(key,)).fetchone()[0],'SUPERSEDED')
    def test_stale_quote_expiry_and_unknown_send(self):
        d,c=payload_from_event(source(),NOW,NOW,NOW);self.o.ingest(d,c,NOW)
        calls=[];self.o.step(quote(NOW-6000),NOW,lambda p:calls.append(p));self.assertFalse(calls)
        self.o.step(quote(NOW+121000),NOW+121000,lambda p:calls.append(p));self.assertFalse(calls)
        self.assertEqual(self.o.db.execute('SELECT state FROM deliveries').fetchone()[0],'EXPIRED')
        d,c=payload_from_event(source(phase='SELL_EXHAUSTION'),NOW+182000,NOW+182000,NOW+182000);self.o.ingest(d,c,NOW+182000)
        def fail(p):raise TimeoutError()
        self.o.step(quote(NOW+182000),NOW+182000,fail)
        self.assertEqual(self.o.db.execute("SELECT count(*) FROM deliveries WHERE state='UNCERTAIN'").fetchone()[0],1)
    def test_invalidated_silenced_without_rebound_confirmed(self):
        # 1. Send DOWN_START
        d1,c1=payload_from_event(source('B-R00', phase='DOWN_START'),NOW,NOW,NOW);self.o.ingest(d1,c1,NOW)
        self.o.step(quote(NOW),NOW,lambda p:'accepted')
        self.assertEqual(self.o.db.execute("SELECT count(*) FROM deliveries WHERE state='FCM_ACCEPTED'").fetchone()[0],1)
        # 2. INVALIDATED arrives: since REBOUND_CONFIRMED was never accepted, must be SILENT_INVALIDATION
        d2,c2=payload_from_event(source('B-R00', phase='INVALIDATED'),NOW+200000,NOW+200000,NOW+200000);self.o.ingest(d2,c2,NOW+200000)
        res = self.o.step(quote(NOW+200000),NOW+200000,lambda p:'accepted')
        self.assertIsNone(res)
        self.assertEqual(self.o.db.execute("SELECT count(*) FROM deliveries WHERE state='SILENT_INVALIDATION'").fetchone()[0],1)
    def test_future_invalid_and_no_position_inference(self):
        for p in [source(phase='HOLDING_EXHAUSTION'),source('S5')]:
            with self.assertRaises(ValueError):payload_from_event(p,NOW,NOW,NOW)
        with self.assertRaises(ValueError):payload_from_event(source(),NOW+1,NOW,NOW)
        with self.assertRaises(ValueError):payload_from_event(source(),NOW,NOW,NOW+120001)

if __name__=='__main__':unittest.main()
