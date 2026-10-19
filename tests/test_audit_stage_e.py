import copy
import json
import sqlite3
import threading
import unittest
from types import SimpleNamespace
from cryptog.ui_evidence import decision_context, research_summary

class StageETests(unittest.TestCase):
    def test_context_is_exact_closed_snapshot_without_mutating_decision(self):
        snapshot={'atMs':1000,'context':{'atMs':900,**{k:{'close_time':899} for k in ('d1','h4','h1')}}}
        decision={'shortHorizonV2':{'env':{'states':{'d1':'UP','h4':'DOWN','h1':'UP'},'gates':{'S1':True}}},'reasons':['fixture']}
        before=copy.deepcopy(decision)
        result=decision_context(snapshot,decision)
        result['gates']['S1']=False
        self.assertEqual(before,decision)
        self.assertEqual(result['frames']['h4'],{'closeTime':899,'state':'DOWN'})
        self.assertIsNone(decision_context({},{}))

    def test_summary_separates_kind_cost_and_legacy_excludes_uncertain(self):
        db=sqlite3.connect(':memory:')
        self.addCleanup(db.close)
        db.executescript('CREATE TABLE candidates(id,module,rule_version); CREATE TABLE shadow_positions(id,kind,opened_ms,closed_ms); CREATE TABLE labels(position_id,candidate_id,net_pct,payload);')
        db.execute('INSERT INTO candidates VALUES(?,?,?)',('c','S1','short-horizon-v2'))
        for i,(kind,net,cost,eligible,version) in enumerate([
            ('SHADOW',1,.24,True,'settlement-v2.1'),('SHADOW',-.5,.24,True,'settlement-v2.1'),
            ('SHADOW',-.4,.24,True,'settlement-v2.1'),('PAPER',2,.24,True,'settlement-v2.1'),
            ('SHADOW',3,.6,True,'settlement-v2.1'),('SHADOW',8,.24,False,'settlement-v2.1'),
            ('SHADOW',9,.11,True,'legacy')]):
            db.execute('INSERT INTO shadow_positions VALUES(?,?,?,?)',(str(i),kind,100+i,200+i))
            db.execute('INSERT INTO labels VALUES(?,?,?,?)',(str(i),'c',net,json.dumps({'eligibleForValidation':eligible,'executionModelVersion':version,'costSnapshot':{'frictionPct':cost,'costModelVersion':'cost-v2'}})))
        ledger=SimpleNamespace(lock=threading.RLock(),store=SimpleNamespace(db=db))
        result=research_summary(ledger,1000)
        self.assertEqual(result['excluded'],2)
        self.assertEqual(len(result['groups']),3)
        group=result['groups'][0]
        self.assertEqual(group['trades'],3)
        self.assertEqual(group['targetRate'],1/3)
        self.assertAlmostEqual(group['expectancyPct'],.1/3)
        self.assertAlmostEqual(group['sumNetDrawdownPct'],.9)
        self.assertEqual(group['maxConsecutiveLosses'],2)
        self.assertIsNone(research_summary(None,1000))

if __name__=='__main__':unittest.main()
