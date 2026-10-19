import json
import tempfile
import unittest
from pathlib import Path
from cryptog.cost_model import cost_snapshot, position_fraction_pct
from cryptog.cost_risk import entry_is_valid
from cryptog.engine_v2 import plan_issue
from cryptog.v2_tracker import open_state, advance
from cryptog.barriers import label_v2
from cryptog.ledger import Ledger
from cryptog.execution_accounting import execution_summary

M=60_000
T=1_800_000_000_000

def sig(at=T, cost=.6):
 return dict(alert_id='stage-b', module='S1', rule_version='short-horizon-v2',timestamp=at, entry_price=100.,stop_loss=99.5,target_tp1=101.2,target_tp2=103.,entry_min=99.95,entry_max=100.05,expires_at=at+30*M,invalidation_price=99.6,cost_snapshot=cost_snapshot(at,{'frictionPct':cost}))
def bar(t, low=100., high=100.3, close=100.2):
 return dict(time=t,close_time=t+M-1,open=100.,low=low,high=high,close=close)

class StageBTests(unittest.TestCase):
 def test_cost_gate_and_settlement_use_point_six(self):
  s=sig(); q=dict(symbol='BTCUSDT',ask_price=100.,timestamp=T)
  self.assertFalse(entry_is_valid(s,q,T))
  self.assertIsNotNone(plan_issue(dict(stop=99.5,tp1=101.2,entry_min=99.95,entry_max=100.05,invalidation=99.6,cost_snapshot=s['cost_snapshot'])))
  self.assertAlmostEqual(position_fraction_pct(.5,.6),.5/1.1*100)
  state=open_state(s);self.assertAlmostEqual(state['breakeven'],100.6)
  advance(state,[bar(T,99.4)],[])
  self.assertEqual(state['pnlPct'],-1.1)
  self.assertEqual(state['r'],-1.)
  self.assertEqual(label_v2(s,[bar(T,99.4)],[])['pnlPct'],state['pnlPct'])
 def test_floor_future_and_discount_evidence(self):
  self.assertEqual(cost_snapshot(T,{'frictionPct':.11})['frictionPct'],.24)
  self.assertEqual(cost_snapshot(T,{'frictionPct':.6,'availableAtMs':T+1})['frictionPct'],.24)
  self.assertEqual(cost_snapshot(T,{'frictionPct':.19,'bnbDiscount':True})['frictionPct'],.24)
  self.assertEqual(cost_snapshot(T,{'frictionPct':.19,'bnbDiscount':True,'bnbVerified':True})['frictionPct'],.19)
 def test_entry_minute_is_not_skipped_or_declared_certain(self):
  state=open_state(sig(T+30000,.24)); advance(state,[bar(T,99.4)],[])
  self.assertEqual(state['filledAt'],T+30000)
  self.assertEqual(state['pathStatus'],'PATH_UNCERTAIN')
  self.assertFalse(state['eligibleForValidation'])
  self.assertEqual(state['conservativePnlPct'],-.74)
 def test_complete_post_fill_ticks_ignore_known_pre_fill_low(self):
  state=open_state(sig(T+30000,.24));b=bar(T,99.4)
  b.update(tickCoverage={'complete':True,'fromMs':T,'toMs':T+M},executionTicks=[{'atMs':T+10000,'price':99.4},{'atMs':T+30000,'price':100.},{'atMs':T+59999,'price':100.2}])
  advance(state,[b],[])
  self.assertEqual(state['phase'],'OPEN')
  self.assertNotEqual(state['pathStatus'],'PATH_UNCERTAIN')
 def test_tp1_on_last_bar_closes_remainder(self):
  s=sig(cost=.24); path=[bar(T+i*M) for i in range(359)]+[bar(T+359*M,100.,101.3,101.)]
  state=open_state(s);advance(state,path,[])
  self.assertEqual(state['closedAt'],T+360*M)
  self.assertEqual(state['outcome'],'TP1_MAX_HOLD')
  self.assertEqual([l['kind'] for l in state['legs']],['TP1','MAX_HOLD'])
  self.assertEqual(sum(l['fraction'] for l in state['legs']),1)
  self.assertEqual(state['pnlPct'],.86)
 def test_after_deadline_target_not_credited(self):
  state=open_state(sig(cost=.24));state['timeChecked']=True
  advance(state,[bar(T+360*M,100.,104.,104.)],[])
  self.assertEqual(state['closedAt'],T+360*M)
  self.assertEqual(state['remaining'],0)
  self.assertFalse(any(l['kind'].startswith('TP') for l in state['legs']))
  self.assertFalse(state['eligibleForValidation'])
 def test_stop_priority_and_ninety_minute(self):
  state=open_state(sig(cost=.24));advance(state,[bar(T,99.,104.,101.)],[])
  self.assertEqual(state['outcome'],'STOP')
  state=open_state(sig(cost=.24));advance(state,[bar(T+i*M,100.,100.1,100.1) for i in range(90)],[])
  self.assertEqual(state['outcome'],'TIME_STOP');self.assertEqual(state['closedAt'],T+90*M)
 def test_shared_actual_cashflow_cases(self):
  data=json.loads((Path(__file__).parent/'stage_b_cashflows.json').read_text())
  for case in data:
   result=execution_summary(case['fills'])
   self.assertAlmostEqual(result['wholeTradeNetPct'],case['expectedPct'],places=8)
   self.assertTrue(result['closed'])
 def test_replay_preserves_original_and_is_idempotent(self):
  with tempfile.TemporaryDirectory() as folder:
   ledger=Ledger(str(Path(folder)/'research.db'))
   try:
    opened=ledger.record_candidate(sig(cost=.24))
    pid=opened['shadowId']
    ledger.settle([bar(T,99.4)],[])
    original=ledger.label_for(pid)
    replay=ledger.replay_label(pid,[bar(T,99.4)],[],T+M)
    again=ledger.replay_label(pid,[bar(T,99.4)],[],T+2*M)
    self.assertEqual(replay['id'],again['id'])
    self.assertEqual(original,ledger.label_for(pid))
    self.assertEqual(replay['originalLabelId'],original['id'])
    self.assertAlmostEqual(ledger.label_quality()['conservativeMeanPct'],-.74)
   finally:ledger.close()
 def test_unknown_fees_do_not_manufacture_closed_trade(self):
  fills=json.loads((Path(__file__).parent/'stage_b_cashflows.json').read_text())[0]['fills']
  fills[0]['commission']=None
  result=execution_summary(fills)
  self.assertIsNone(result['wholeTradeNetPct']);self.assertFalse(result['closed'])
 def test_partial_profit_is_not_whole_trade_profit(self):
  fills=json.loads((Path(__file__).parent/'stage_b_cashflows.json').read_text())[0]['fills'][:2]
  result=execution_summary(fills)
  self.assertAlmostEqual(result['realizedNetUsdt'],.4)
  self.assertIsNone(result['wholeTradeNetPct']);self.assertEqual(result['inventory'],.5)
 def test_no_future_imports_or_duplicate_fills_in_calibration(self):
  with tempfile.TemporaryDirectory() as folder:
   ledger=Ledger(str(Path(folder)/'research.db'))
   try:
    f=json.loads((Path(__file__).parent/'stage_b_cashflows.json').read_text())[0]['fills'][0]
    ledger.record_buy(f)
    self.assertEqual(ledger.working_cost(f['executedAtMs'])['source'],'PRIOR')
   finally:ledger.close()

if __name__=='__main__':unittest.main()
