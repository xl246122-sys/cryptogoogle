import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scratch'))
from cryptog.wave_integration import WaveIntegration, paper_position, risk_check

NOW=1800000000000
CONFIG=dict(protocolId='C-CONTRACT-TEST-NOT-PRODUCTION',minStopPct=.35,maxStopPct=2.,minNetPct=.8,
    minRR=1.2,costPct=.24,maxQuoteAgeMs=10000,maxHoldMinutes=360,priceMode='REFERENCE_PLUS_ROUND_TRIP_COST')
PLAN=dict(entryLow=99.9,entryHigh=100.1,stop=99.5,target=101.5,expiresAt=NOW+60000)
QUOTE=dict(ask=100.,bid=100.,atMs=NOW,healthy=True)


def buy(id='buy1',at=NOW,price=100,amount=500):
    return dict(eventId=id,actedAtMs=at,recordType='SIM_BUY',strategy='QUICK_PAPER_V2',entryPrice=price,
        positionSize=amount,costSnapshot=dict(frictionPct=.24,applicableAtMs=at,costModelVersion='test'))


def sell(id='sell1',at=NOW+1,price=100,amount=250,exit_price=101):
    return dict(eventId=id,actedAtMs=at,recordType='USER_CLOSE',strategy='QUICK_PAPER_V2',entryPrice=price,
        positionSize=amount,exitPrice=exit_price)


class WaveTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=str(Path(self.tmp.name)/'wave.sqlite3');self.store=WaveIntegration(self.path)
    def tearDown(self): self.store.close();self.tmp.cleanup()
    def record(self,phase='DOWN_START',at=NOW,**kw):
        return self.store.record(event_id='event',parent_id='parent',phase=phase,decision_ms=at,feature_ms=at,
            evidence={'stateKey':phase},**kw)

    def test_observations_bypass_buy_profit_gate_but_never_buy(self):
        for i,phase in enumerate(['DOWN_START','SELL_EXHAUSTION']):
            p=self.record(phase,NOW+i,plan=PLAN)
            self.assertIsNone(p['plan']);self.assertIsNone(p['risk']);self.assertFalse(p['tradeEligible'])
            self.assertEqual(p['signalType'],'OBSERVE')
        p=self.record('REBOUND_CONFIRMED',NOW+2,plan=PLAN,config=CONFIG,quote=QUOTE)
        self.assertEqual(p['risk']['status'],'PASS_RESEARCH_ONLY');self.assertFalse(p['tradeEligible'])

    def test_new_quote_recomputes_independent_module_risk(self):
        plan=PLAN|dict(stop=98.5,target=103)
        self.assertEqual(risk_check(plan,CONFIG,QUOTE,NOW)['status'],'PASS_RESEARCH_ONLY')
        self.assertEqual(risk_check(plan,CONFIG|dict(maxStopPct=1.2),QUOTE,NOW)['reason'],'STOP_DISTANCE')
        self.assertEqual(risk_check(PLAN,CONFIG,QUOTE|dict(ask=100.2),NOW)['reason'],'ENTRY_RANGE')
        self.assertEqual(risk_check(PLAN,CONFIG|dict(costPct=.8),QUOTE,NOW)['reason'],'NET_SPACE')
        self.assertEqual(risk_check(PLAN,CONFIG,QUOTE|dict(atMs=NOW-10001),NOW)['reason'],'QUOTE_STALE_OR_GAP')
        self.assertEqual(risk_check(PLAN,CONFIG|dict(priceMode='SLIPPAGE_ALREADY_IN_PRICE'),QUOTE,NOW)['reason'],'UNSUPPORTED_COST_MODE')

    def test_persistence_revision_and_device_dedup(self):
        p=self.record();self.assertEqual(self.record(at=NOW+1)['revision'],1)
        self.assertTrue(self.store.enqueue('phone1','event',1));self.assertFalse(self.store.enqueue('phone1','event',1))
        self.assertTrue(self.store.enqueue('phone2','event',1))
        self.store.close();self.store=WaveIntegration(self.path)
        self.assertFalse(self.store.enqueue('phone1','event',1))
        p=self.record('SELL_EXHAUSTION',NOW+2);self.assertEqual(p['revision'],2)
        self.assertTrue(self.store.enqueue('phone1','event',2))
        self.assertEqual(self.store.receipt('phone1','event',2,'PLATFORM_ACCEPTED'),'PLATFORM_ACCEPTED')
        self.assertEqual(self.store.receipt('phone1','event',2,'OPENED'),'OPENED')
        self.assertEqual(self.store.receipt('phone1','event',2,'RECEIVED'),'OPENED')

    def test_expiration_and_final_delivery_recheck(self):
        self.record('REBOUND_CONFIRMED',plan=PLAN,config=CONFIG,quote=QUOTE)
        with self.assertRaisesRegex(ValueError,'DELIVERY_RISK'):self.store.delivery_payload('event',1,NOW+1,QUOTE|dict(ask=103),CONFIG)
        self.store.expire(NOW+60000);p=self.store.messages()[0]
        self.assertEqual(p['lifecycle'],'INVALIDATED');self.assertEqual(p['reason'],'EXPIRED')
        with self.assertRaisesRegex(ValueError,'STALE_DELIVERY'): self.store.delivery_payload('event',1,NOW+60001,QUOTE,CONFIG)
        with self.assertRaisesRegex(ValueError,'TERMINAL'):self.record('REBOUND_CONFIRMED',NOW+60002,plan=PLAN,config=CONFIG,quote=QUOTE)

    def test_future_and_out_of_order_fail_closed(self):
        self.record(at=NOW+1)
        with self.assertRaisesRegex(ValueError,'OUT_OF_ORDER'): self.record(at=NOW)
        with self.assertRaisesRegex(ValueError,'FUTURE'):self.store.record(event_id='x',parent_id='p',phase='DOWN_START',decision_ms=NOW,feature_ms=NOW+1,evidence={})
        with self.assertRaisesRegex(ValueError,'OUTCOME'):self.store.record(event_id='x',parent_id='p',phase='DOWN_START',decision_ms=NOW,feature_ms=NOW,evidence={'nested':{'OUTCOME_profit':3}})

    def test_same_close_ordered_transitions_require_source_revision(self):
        self.record(source_revision=1)
        p=self.record('SELL_EXHAUSTION',source_revision=2)
        self.assertEqual(p['revision'],2)
        with self.assertRaisesRegex(ValueError,'CONFLICTING_EVENT_TIME'):self.record('DOWN_START',source_revision=1)
        p=self.record('DOWN_START',source_revision=3,reason='LOW_BROKEN')
        self.assertEqual(p['revision'],3)

    def test_paper_partial_add_and_cost_once(self):
        a=[buy(),sell()];p=paper_position(a,'owner')
        self.assertAlmostEqual(p['remainingQuantity'],2.5);self.assertAlmostEqual(p['remainingCostUsdt'],250)
        self.assertAlmostEqual(p['costReserveUsdt'],.6);self.assertAlmostEqual(p['realizedNetUsdt'],1.9)
        add=paper_position(a+[buy('buy2',NOW+2,price=200)],'owner')
        self.assertAlmostEqual(add['remainingQuantity'],5);self.assertAlmostEqual(add['remainingCostUsdt'],750)
        self.assertAlmostEqual(add['costReserveUsdt'],1.8);self.assertNotEqual(add['revision'],p['revision'])
        self.assertEqual(paper_position(a+[a[0]],'owner'),p)
        with self.assertRaisesRegex(ValueError,'SELL'):paper_position([buy(),sell(amount=600)],'owner')

    def test_position_scope_and_closed_inventory_stops_reminders(self):
        args=dict(event_id='position-event',parent_id='position-parent',decision_ms=NOW+10,feature_ms=NOW+10,
                  evidence={'stateKey':'E1'},quote=QUOTE)
        self.assertIsNone(self.store.observe_paper([], 'owner',**args))
        p=self.store.observe_paper([buy()],'owner',**args)
        self.assertIn('风险退出',p['title']);self.assertEqual(self.store.messages(),[])
        self.assertEqual(self.store.messages('other'),[]);self.assertEqual(len(self.store.messages('owner')),1)
        with self.assertRaisesRegex(ValueError,'OWNER'):self.store.enqueue('phone','position-event',1,owner='other')
        self.assertTrue(self.store.enqueue('phone','position-event',1,owner='owner'))
        self.store.observe_paper([buy(),sell(amount=500)],'owner',**(args|dict(decision_ms=NOW+11,feature_ms=NOW+11)))
        closed=self.store.messages('owner')[0];self.assertEqual(closed['lifecycle'],'INVALIDATED')
        self.assertEqual(closed['position']['remainingQuantity'],0)
        self.store.observe_paper([buy(),sell(amount=500)],'owner',**(args|dict(decision_ms=NOW+12,feature_ms=NOW+12)))
        self.assertEqual(self.store.messages('owner')[0]['revision'],closed['revision'])

    def test_profit_label_and_stop_priority(self):
        pos=paper_position([buy()],'owner')
        p=self.record('HOLDING_EXHAUSTION',position=pos,quote=QUOTE|dict(bid=101))
        self.assertAlmostEqual(p['position']['estimatedNetUsdt'],3.8);self.assertIn('止盈',p['title'])
        p=self.store.record(event_id='stop',parent_id='parent',phase='HOLDING_EXHAUSTION',decision_ms=NOW,
            feature_ms=NOW,evidence={'priority':'STOP'},position=pos,quote=QUOTE|dict(bid=101))
        self.assertIn('风险退出',p['title'])


if __name__=='__main__': unittest.main()
