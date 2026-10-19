import tempfile, threading, unittest
from pathlib import Path
from types import SimpleNamespace
from cryptog.research_feed import SpotResearchFeed, validated
from cryptog.kline_store import ResearchStore, INTERVAL_MS
from cryptog.account_context import AccountContext, FRESH_MS
from cryptog.storage import EventStore
from cryptog.ledger import Ledger
from cryptog.execution_sync import mirror, reconcile, health
from cryptog.execution_accounting import execution_summary, paper_close_cost
from cryptog.review_bridge import review_options, review_status
from cryptog.funnel import stage, report

T=1_800_000_000_000
def raw(t,span):return [t,'100','102','99','101','10',t+span-1,'0',0,'4']
def fill(fid,price=100):return dict(fillId=fid,positionId='c-position',side='BUY',source='MANUAL',price=price,quantity=.01,executedAtMs=T,commission=0,commissionAsset='USDT',timeApproximate=False,referencePrice=100,referenceAtMs=T-1000)
class StageCTests(unittest.TestCase):
 def test_closed_validation(self):
  self.assertEqual(len(validated([raw(T,60000),raw(T+60000,60000)],'1m',T+60000)),1)
  with self.assertRaises(ValueError):validated([raw(T+1,60000)],'1m',T+120000)
  bad=raw(T,60000);bad[4]='NaN'
  with self.assertRaises(ValueError):validated([bad],'1m',T+60000)
 def test_six_intervals_restart_and_gap_repair(self):
  with tempfile.TemporaryDirectory() as folder:
   path=str(Path(folder)/'r.db')
   def fetch(tf,start,end):
    span=INTERVAL_MS[tf]
    return [raw(t,span) for t in range(start,min(end+1,start+1000*span),span)]
   feed=SpotResearchFeed(path,threading.Event(),fetch)
   one=feed.step(T);self.assertTrue(one['healthy']);self.assertEqual([one['coverage'][tf]['count'] for tf in INTERVAL_MS],[300]*6)
   store=ResearchStore(path)
   with store.db:store.db.execute("DELETE FROM klines WHERE interval='1m' AND open_time=?",(T-10*60000,))
   store.close()
   two=SpotResearchFeed(path,threading.Event(),fetch).step(T)
   self.assertTrue(two['healthy']);self.assertEqual(two['coverage']['1m']['count'],300)
   self.assertFalse(feed.status(T+120001)['healthy'])
 def test_unknown_stale_or_uncovered_account(self):
  with tempfile.TemporaryDirectory() as folder:
   store=EventStore(str(Path(folder)/'m.db'));context=AccountContext(store)
   try:
    self.assertIsNone(context.report([],T)['singleTradeRiskBudgetUsdt'])
    context.put({'equityUsdt':500,'allPositionsRecorded':True},T)
    self.assertEqual(context.report([{'plannedRiskUsdt':2}],T)['totalPlannedRiskUsdt'],2)
    self.assertEqual(context.report([],T)['singleTradeRiskBudgetUsdt'],2.5)
    self.assertIsNone(context.report([{}],T)['totalPlannedRiskUsdt'])
    self.assertIsNone(context.report([],T+FRESH_MS+1)['singleTradeRiskBudgetUsdt'])
    with self.assertRaises(ValueError):context.put({'equityUsdt':True,'allPositionsRecorded':True},T)
   finally:store.db.close()
 def test_journal_mirror_idempotent_correction_and_retry(self):
  with tempfile.TemporaryDirectory() as folder:
   ledger=Ledger(str(Path(folder)/'r.db'))
   try:
    f=fill('old');a=dict(eventId='a',alertId='c-alert',recordType='MANUAL_FILL',actedAtMs=T,receivedAtMs=T,fill=f,executionSummary=execution_summary([f]))
    self.assertTrue(mirror(ledger,a));self.assertTrue(mirror(ledger,a))
    f2=fill('new',101);b=dict(a,eventId='b',recordType='FILL_CORRECTION',receivedAtMs=T+1,replacesEventId='a',fill=f2,executionSummary=execution_summary([f2]))
    reconcile(ledger,[a,b]);self.assertEqual(health(ledger),{'DONE':2})
    self.assertEqual(ledger.store.db.execute('SELECT old_fill_id,new_fill_id FROM fill_corrections').fetchall(),[('old','new')])
    self.assertEqual(len(ledger.cost_fills()),1)
    failed=dict(a,eventId='bad',fill={})
    # Retry a durable non-fill event after a transient mirror failure.
    original=ledger.on_fill
    ledger.on_fill=lambda *a,**k:(_ for _ in ()).throw(RuntimeError('temporary'))
    retry=dict(a,eventId='retry',fill=fill('retry'))
    self.assertFalse(mirror(ledger,retry));ledger.on_fill=original
    self.assertTrue(mirror(ledger,retry));self.assertEqual(health(ledger),{'DONE':3})
   finally:ledger.close()
 def test_provider_switch_no_key_leak(self):
  for provider in ['DEEPSEEK','GEMINI']:
   ai=SimpleNamespace(get_config=lambda:dict(provider=provider,model='test',apiKey='secret',enabled=True))
   self.assertEqual(review_status(ai)['state'],'READY');self.assertNotIn('secret',str(review_status(ai)))
   self.assertTrue(callable(review_options(ai)['post']))
  ai=SimpleNamespace(get_config=lambda:dict(provider='DEEPSEEK',enabled=False))
  self.assertEqual(review_status(ai)['state'],'DISABLED')
  ai.get_config=lambda:dict(provider='DEEPSEEK',enabled=True)
  self.assertEqual(review_status(ai)['state'],'MISSING_KEY')
 def test_funnel_deduplicates_stages_not_trades(self):
  with tempfile.TemporaryDirectory() as folder:
   ledger=Ledger(str(Path(folder)/'r.db'))
   try:
    stage(ledger,'c',T,'DETECTED');stage(ledger,'c',T+1,'DETECTED');stage(ledger,'c',T+1,'SCREENED','NET_RR')
    self.assertEqual(sum(x['count'] for x in report(ledger)['counts']),2)
   finally:ledger.close()
 def test_paper_cost_frozen_across_partial_close(self):
  rows=[dict(alertId='a',strategy='QUICK_PAPER_V2',recordType='SIM_BUY',positionSize=100,costSnapshot={'frictionPct':.6})]
  action=dict(alertId='a',positionSize=50)
  self.assertAlmostEqual(paper_close_cost(action,rows),.3)
  rows.append(dict(action,strategy='QUICK_PAPER_V2',recordType='USER_CLOSE'))
  self.assertAlmostEqual(paper_close_cost(action,rows),.3)
  with self.assertRaises(ValueError):paper_close_cost(dict(action,positionSize=51),rows)
if __name__=='__main__':unittest.main()
