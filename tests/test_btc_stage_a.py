import sys
import unittest
from pathlib import Path
import numpy as np
import pandas as pd
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from research_btc_stage_a import mark_path,gate_flags,permitted,coverage


class StageATests(unittest.TestCase):
    def test_stop_minute_high_and_close_are_not_available_profit(self):
        bars=np.array([[100,100.3,99.9,100.1],[100,110,90,109]],dtype=float)
        self.assertAlmostEqual(mark_path(bars,0,1,100,.24),-.14)
        self.assertIsNone(mark_path(bars,1,1,100,.24))

    def test_relaxing_min_does_not_relax_net_or_max(self):
        flags=dict(stop_min=True,stop_max=False,net_space=True)
        self.assertFalse(permitted(flags,'MIN',.2))
        flags['net_space']=False
        self.assertTrue(permitted(flags,'MIN',.2))
        self.assertTrue(flags['stop_min'])
        self.assertFalse(permitted(dict(stop_min=False,stop_max=True),'MAX',2.6))

    def test_all_gates_are_recorded_not_just_first(self):
        p=dict(stop=98,target=100.5,entryLow=100.1,entryHigh=100.2,minNet=.8,windowMin=5)
        flags,risk,net=gate_flags(p,100,.24,np.empty((0,4)))
        self.assertTrue(flags['entry_band']);self.assertTrue(flags['stop_max'])
        self.assertTrue(flags['net_space']);self.assertTrue(flags['net_rr'])

    def test_future_warning_does_not_cover_past_opportunity(self):
        opportunities=pd.DataFrame([dict(profile='FAST',confirmMs=2000000,success=True)])
        warnings=pd.DataFrame([dict(method='DOCUMENT_FIXED',windowMin=5,triggerMs=2000001,triggerIndex=1)])
        details=pd.DataFrame(columns=['method','windowMin','triggerIndex','openedMs','baselinePass'])
        summary,_=coverage(opportunities,warnings,details)
        row=summary[summary.method=='DOCUMENT_FIXED'].iloc[0]
        self.assertEqual(row.missedPct,100)

    def test_confirmed_but_future_execution_price_is_not_risk_pass_yet(self):
        opportunities=pd.DataFrame([dict(profile='FAST',confirmMs=2000000,success=True)])
        warnings=pd.DataFrame([dict(method='DOCUMENT_FIXED',windowMin=5,triggerMs=1999999,triggerIndex=1)])
        details=pd.DataFrame([dict(method='DOCUMENT_FIXED',windowMin=5,triggerIndex=1,openedMs=2060000,baselinePass=True)])
        summary,matches=coverage(opportunities,warnings,details)
        row=summary[summary.method=='DOCUMENT_FIXED'].iloc[0]
        self.assertEqual(row.warnedRiskPass,0)
        self.assertEqual(row.warnedPendingExecution,1)


if __name__=='__main__':
    unittest.main()
