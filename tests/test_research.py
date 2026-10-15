import copy,unittest
from unittest.mock import patch
from test_stage1 import fixture,NOW
from cryptog.research import evaluate_research
from cryptog.evaluation import evaluate
from cryptog.clock import at_time
from cryptog.storage import EventStore,decode_event

def sample():
 s=fixture().snapshot(NOW)
 for i,c in enumerate(s['series']['5m']):c.update(open=100.4,close=100.4 if i%2 else 101.6,high=104.4,low=100.)
 for c in s['series']['1m']:c.update(high=101.5,low=100.,open=100.3,close=100.3,volume=100.,taker_buy_base=60.)
 for c in s['series']['1m'][-6:-3]:c['taker_buy_base']=40.
 s['series']['1m'][-2]['open']=100.5
 s['series']['1m'][-1].update(open=100.2,close=100.4,taker_buy_base=70.)
 s['ticker']['change24h']=-2.
 # Avoid a nearer resistance in the other timeframes.
 for name in ('15m','1h'):
  for c in s['series'][name]:c['high']=103.
 return s

def research(s):
 with at_time(s['atMs']):return evaluate_research(s['series'],s['ticker'],s['book'],{'is_bearish':True},s['atMs'])

class ResearchTests(unittest.TestCase):
 def test_baseline_rejection_does_not_short_circuit_shadow(self):
  s=sample()
  with patch('cryptog.evaluation.diagnose_macro_trend',return_value={'trend':'BEARISH','is_bearish':True,'is_strongly_bearish':True,'ma20':102.,'rsi':35.}):
   result=evaluate(s)
  self.assertIsNone(result['signal']);self.assertEqual(result['status'],'WAIT_CONFIRMATION')
  self.assertIn('要求≥5%',result['reasons'][0])
  self.assertEqual(result['research'][1]['status'],'SHADOW_CANDIDATE',result['research'])
 def test_cost_floor_and_stop_width_reject_without_rewriting_structure(self):
  s=sample()
  with patch('cryptog.research.verify_micro_range_reversal',return_value=(True,'passed',95.,105.)):
   result=research(s)
  self.assertTrue(all(r['status']=='REJECTED' for r in result))
  self.assertTrue(any('结构风险' in x for x in result[1]['reasons']))
 def test_real_local_candidate_preserves_structural_cost_gates(self):
  rows=research(sample());r=rows[1]
  self.assertEqual(r['status'],'SHADOW_CANDIDATE',r['reasons'])
  self.assertGreaterEqual(r['candidate']['netTP1'],.4);self.assertGreaterEqual(r['candidate']['netRR'],1.1)
  self.assertEqual(r['candidate']['maxHoldMinutes'],120)
 def test_real_oversold_recovery(self):
  s=sample()
  for i,c in enumerate(s['series']['5m'][-21:]):
   close=102-i*.1 if i<20 else 100.9
   c.update(open=close,close=close,high=close+.2,low=close-.2)
  r=research(s)[0];self.assertEqual(r['status'],'SHADOW_CANDIDATE',r['reasons'])
 def test_nearest_barrier_cannot_be_skipped_and_stop_not_tightened(self):
  s=sample();r=research(s)[1];stop=r['candidate']['stopLoss']
  s['series']['15m'][-5]['high']=100.6
  with patch('cryptog.research.observed_resistances',return_value=[100.6,105.]):
   r=research(s)[1];self.assertEqual(r['status'],'REJECTED');self.assertTrue(any('净空间' in x for x in r['reasons']))
  self.assertLess(stop,100.)
 def test_bad_flow_and_waterfall_rejected(self):
  s=sample()
  for c in s['series']['1m'][-3:]:c['taker_buy_base']=10.
  self.assertEqual(research(s)[1]['status'],'REJECTED')
  with patch('cryptog.research.diagnose_cascade_downtrend',return_value=(True,'瀑布')):
   self.assertEqual(research(sample())[1]['status'],'REJECTED')
 def test_stale_future_and_replay_determinism(self):
  s=sample();a=copy.deepcopy(s);self.assertEqual(evaluate(s),evaluate(s));self.assertEqual(s,a)
  s['series']['1m'][-1]['close_time']=NOW+1
  self.assertEqual(evaluate(s)['research'],[])
  s=sample();s['healthy']=False;self.assertEqual(evaluate(s)['research'],[])
 def test_research_failure_does_not_modify_baseline(self):
  s=sample();before=evaluate(s)
  with patch('cryptog.research.evaluate_research',side_effect=RuntimeError('test')):after=evaluate(s)
  self.assertEqual(before['signal'],after['signal']);self.assertEqual(before['reasons'],after['reasons'])
  self.assertEqual(after['research'][0]['status'],'ERROR')
 def test_new_variants_metadata(self):
  rows=research(sample())[2:]
  self.assertEqual(len(rows),5)
  for row in rows:
   self.assertEqual(row['mode'],'SHADOW')
   self.assertEqual(row['version'],'minute-session-shadow-v1')
   self.assertIn(360,row['parameters']['holdComparisonMinutes'])
   self.assertIn('realizedVolatility',row)
   self.assertFalse(row['session']['entryPermission'])
 def test_minute_candidate_without_five_percent_drop(self):
  with patch('cryptog.research.shock_measure',return_value={'dropPct':1.6,'reclaim':True}):
   row=research(sample())[2]
  self.assertEqual(row['status'],'SHADOW_CANDIDATE',row['reasons'])
  self.assertGreaterEqual(row['candidate']['netRR'],1.1)
 def test_short_box_break_invalidates(self):
  s=sample();s['series']['1m'][-1]['low']=99.
  with patch('cryptog.research.stable_range_box',return_value={'low':100.,'high':104.,'mid':102.}):
   row=research(s)[5]
  self.assertEqual(row['status'],'REJECTED')
  self.assertFalse(next(c for c in row['checks'] if c['name']=='箱体仍有效')['passed'])
 def test_shadow_journal_dedup_never_enters_outbox(self):
  s=sample();rows=research(s)
  store=EventStore(':memory:');decision={'research':rows,'signal':None}
  store.record_evaluation(s,decision)
  s2=copy.deepcopy(s);s2['atMs']+=1000;store.record_evaluation(s2,decision)
  self.assertEqual(store.db.execute("select count(*) from events where kind='RESEARCH_CANDIDATE'").fetchone()[0],1)
  self.assertEqual(store.db.execute('select count(*) from outbox').fetchone()[0],0)
  self.assertEqual(store.db.execute('select count(*) from opportunities').fetchone()[0],0)
  store.close()

if __name__=='__main__':unittest.main()

