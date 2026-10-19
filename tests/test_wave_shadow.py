import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scratch'))
from cryptog.wave_shadow import ShadowStore, extract_quote


def snapshot(now=100000):
    return dict(ticker=dict(bid_price=99.99,ask_price=100.,timestamp=now-20),
        depthReceivedAtMs=now-10,clockOffsetMs=0,clockUncertaintyMs=1,
        healthy=True,book=dict(is_valid=True),depthUpdateId=4)


class ShadowTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.path=Path(self.temp.name)/'shadow.sqlite3'
        self.store=ShadowStore(self.path)

    def tearDown(self):
        self.store.db.close()
        self.temp.cleanup()

    def test_quote_requires_real_depth_time_and_healthy_clock(self):
        self.assertTrue(extract_quote(snapshot(),100000)['healthy'])
        for patch in [dict(depthReceivedAtMs=None),dict(clockUncertaintyMs=1001),dict(healthy=False)]:
            self.assertFalse(extract_quote(dict(snapshot(),**patch),100000)['healthy'])
        self.assertFalse(extract_quote(snapshot(),110000)['healthy'])
        bad=snapshot();bad['ticker']['ask_price']=float('nan')
        self.assertFalse(extract_quote(bad,100000)['healthy'])

    def test_restart_idempotency_and_future_rejection(self):
        self.assertTrue(self.store.quote('q',snapshot(),100000)[1])
        self.store.db.close();self.store=ShadowStore(self.path)
        self.assertFalse(self.store.quote('q',snapshot(),100000)[1])
        with self.assertRaises(ValueError):self.store.event('future',100001,100000,{},1)
        self.assertTrue(self.store.event('e',99999,100000,{},1))
        self.assertFalse(self.store.event('e',99999,100010,{},1))

    def test_fee_gates_and_model_account_no_actual_fill(self):
        p=dict(group='B-R00',entryLow=99.9,entryHigh=100.1,stop=99.6,target=101.1,
            minNet=.8,window=5,holdMinutes=30,exitMode='E0')
        self.store.register_plan('c',p,100000,100000)
        self.store.step_positions(extract_quote(snapshot(),100000))
        states=dict(self.store.db.execute('SELECT state,count(*) FROM candidates GROUP BY state'))
        self.assertEqual(states['MODEL_OPENED'],1)
        self.assertEqual(states['NET_SPACE'],2)
        self.assertEqual(states['PENDING'],6)
        q=extract_quote(snapshot(102000),102000);q['bid']=101.2;q['ask']=101.21
        self.store.step_positions(q)
        result=json.loads(self.store.db.execute('SELECT payload FROM trades').fetchone()[0])
        self.assertAlmostEqual(result['netPct'],.96)
        self.assertFalse(result['eligibleForValidation'])
        self.assertGreater(self.store.db.execute('SELECT cash FROM accounts').fetchone()[0],500)

    def test_gap_does_not_fill_late_signal(self):
        p=dict(group='B-R00',entryLow=99.9,entryHigh=100.1,stop=99.5,target=102,
            minNet=.8,window=5,holdMinutes=30,exitMode='E0')
        self.store.register_plan('c',p,100000,100000)
        self.store.step_positions(extract_quote(snapshot(115000),115000))
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM candidates WHERE state='LATE_OR_GAP'").fetchone()[0],3)

    def test_receipt_is_not_one_way_or_display_evidence(self):
        source=sqlite3.connect(':memory:')
        source.executescript('CREATE TABLE exit_attempts(delivery_id,attempt,started_ms,finished_ms,result); CREATE TABLE exit_receipts(delivery_id,kind,client_ms,server_ms);')
        source.execute("INSERT INTO exit_attempts VALUES('secret-device-delivery',1,100,120,'FCM_ACCEPTED')")
        self.store.collect_delivery(source,1)
        first=json.loads(self.store.db.execute('SELECT payload FROM delivery').fetchone()[0])
        self.assertIsNone(first['receiptRoundTripMs'])
        source.execute("INSERT INTO exit_receipts VALUES('secret-device-delivery','OPENED',900000,400)")
        self.store.collect_delivery(source,1)
        rows=[json.loads(r[0]) for r in self.store.db.execute('SELECT payload FROM delivery')]
        opened=next(r for r in rows if r['receiptKind']=='OPENED')
        self.assertEqual(opened['receiptRoundTripMs'],300)
        self.assertIsNone(opened['oneWayDeliveryMs'])
        self.assertFalse(opened['displayConfirmed'])
        self.assertNotIn('secret-device-delivery',str(rows))
        source.close()


if __name__=='__main__':unittest.main()
