import json
import math
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scratch'))
from cryptog.wave_holding import owned_actions,position_snapshot,exhaustion,holding_payload,HoldingMonitor
from cryptog.wave_push import ResearchOutbox,transport_fields,recheck
NOW=1792368060000
OWNER='a'*64
def buy():return dict(eventId='buy1',strategy='QUICK_PAPER_V2',recordType='SIM_BUY',actedAtMs=NOW-1800000,
    entryPrice=100.,positionSize=500.,costSnapshot=dict(frictionPct=.24,applicableAtMs=NOW-1800000),authenticatedOwner=OWNER)
def quote():return dict(bid=101.,ask=101.01,sourceMs=NOW,clockOffsetMs=0,observedMs=NOW,healthy=True)

class HoldingTests(unittest.TestCase):
    def test_owner_and_explicit_legacy_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'actions';a=buy();other=dict(a,eventId='other',authenticatedOwner='b'*64);legacy=dict(a,eventId='legacy');legacy.pop('authenticatedOwner')
            path.write_text(''.join(json.dumps(x)+'\n' for x in [a,other,legacy]))
            self.assertEqual([x['eventId'] for x in owned_actions(path,OWNER)],['buy1'])
            self.assertEqual(len(owned_actions(path,OWNER,['legacy'])),2)
            path.write_text(json.dumps(a))
            with self.assertRaisesRegex(ValueError,'APPEND'):owned_actions(path,OWNER)

    def test_partial_close_cost_and_live_price_wording(self):
        actions=[buy(),dict(buy(),eventId='sell',recordType='USER_CLOSE',actedAtMs=NOW-60000,exitPrice=101.,positionSize=200.)]
        p=position_snapshot(actions,OWNER,NOW);self.assertEqual(p['remainingQuantity'],3.)
        self.assertAlmostEqual(p['costReserveUsdt'],.72)
        d=holding_payload(p,dict(featureMs=NOW),quote(),NOW,'holding-test',1)
        self.assertAlmostEqual(d['position']['estimatedNetUsdt'],2.28)
        self.assertIn('获利了结',transport_fields(d)[0]);self.assertNotIn(OWNER,json.dumps(d))
        q=quote();q['bid']=99.;d=recheck(d,None,q,NOW)
        self.assertNotIn('获利了结',transport_fields(d)[0]);self.assertIn('风险',transport_fields(d)[0])
        actions.append(dict(buy(),eventId='sell-rest',recordType='USER_CLOSE',actedAtMs=NOW,exitPrice=101.,positionSize=300.))
        self.assertEqual(position_snapshot(actions,OWNER,NOW)['remainingQuantity'],0)

    def test_dynamic_closed_bar_detector_and_gap(self):
        n=92*1440+10;start=NOW//86400000*86400000-92*86400000
        values=[100+math.sin(i*.2) for i in range(n)]
        values[-23:]=[100+i for i in range(20)]+[118.,117.,116.]
        rows=[(start+i*60000,c,c+.05,c-.05,c) for i,c in enumerate(values)]
        now=rows[-1][0]+60000
        result=exhaustion(rows,now-30*60000,now)
        self.assertTrue(result['triggered']);self.assertLess(result['rsi90'],90)
        self.assertFalse(exhaustion(rows,now-60000,now)['triggered'],'pre-buy overbought must not trigger')
        with self.assertRaisesRegex(ValueError,'GAP'):exhaustion(rows[:100]+rows[101:],now-1800000,now)
        with self.assertRaisesRegex(ValueError,'STALE'):exhaustion(rows,now-1800000,now+120001)

    def test_close_supersedes_pending_and_updates_sent(self):
        with tempfile.TemporaryDirectory() as tmp:
            o=ResearchOutbox(Path(tmp)/'out.db');db=sqlite3.connect(':memory:');m=HoldingMonitor(o,db)
            p=position_snapshot([buy()],OWNER,NOW);ev=dict(featureMs=NOW)
            d=holding_payload(p,ev,quote(),NOW,'test',1);o.ingest(d,None,NOW)
            o.put('holdingTracked',{'test':dict(position=p,evidence=ev,closed=False)})
            actions=[buy(),dict(buy(),eventId='closed',recordType='USER_CLOSE',actedAtMs=NOW,exitPrice=101.,positionSize=500.)]
            m.tick(actions,OWNER,None,NOW+1)
            self.assertEqual(o.db.execute("SELECT state FROM deliveries WHERE revision=1").fetchone()[0],'SUPERSEDED')
            calls=[];o.step(None,NOW+1,lambda d:calls.append(d));self.assertFalse(calls)
            o.db.close();db.close()

if __name__=='__main__':unittest.main()
