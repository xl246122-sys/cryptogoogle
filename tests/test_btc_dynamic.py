import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from research_btc_dynamic import daily_levels, gate, settle, simulate


class DynamicStudyTests(unittest.TestCase):
    def test_future_and_current_bar_do_not_change_threshold(self):
        values=np.arange(120,dtype=float)
        returns=np.linspace(-.01,.02,120)
        before=daily_levels({5:values},returns,100,90)
        values[100:]=999999
        returns[100:]=999999
        self.assertEqual(before,daily_levels({5:values},returns,100,90))
        self.assertAlmostEqual(before[0][5][95],94.55)

    def test_missing_training_feature_fails(self):
        values=np.ones(100);values[50]=np.nan
        with self.assertRaisesRegex(ValueError,'training'):
            daily_levels({5:values},np.ones(100),100,90)

    def test_stop_first_and_gap_loss(self):
        bars=np.array([[100,105,95,100],[100,100,100,100]],dtype=float)
        self.assertEqual(settle(bars,0,2,98,104),(0,98.,'STOP'))
        bars[0]=[96,105,95,100]
        self.assertEqual(settle(bars,0,2,98,104),(0,96.,'STOP_GAP'))

    def test_tail_is_censored_even_if_first_bar_hits_target(self):
        self.assertIsNone(settle(np.array([[100,110,99,105]]),0,2,98,104))

    def test_cost_and_risk_gates_recompute_at_entry(self):
        p=dict(entryLow=99.9,entryHigh=100.1,stop=99.5,target=101.15,minNet=.8,windowMin=5)
        self.assertIsNone(gate(p,100,.24))
        self.assertEqual(gate(p,100,.4),'net_space')
        self.assertEqual(gate(p,100.2,.24),'entry_band')
        self.assertEqual(gate(p|dict(stop=98),100,.24),'stop_distance')

    def test_only_one_position_and_one_entry_per_parent(self):
        bars=pd.DataFrame(dict(time=np.arange(10)*60000,open=np.full(10,100.),
                               high=np.full(10,100.1),low=np.full(10,99.9),close=np.full(10,100.)))
        p=dict(method='TEST',windowMin=5,triggerIndex=0,parentIndex=0,confirmIndex=0,
               reference=100,entryLow=99.9,entryHigh=100.1,stop=99.5,target=101.15,holdMinutes=2,minNet=.8)
        plans=[p,p|dict(confirmIndex=1,parentIndex=1),p|dict(confirmIndex=4)]
        trades,counts,capital,curve=simulate(bars,plans,0,.24,0)
        self.assertEqual(len(trades),1)
        self.assertEqual(counts['position_busy'],1)
        self.assertEqual(counts['parent_duplicate'],1)
        self.assertLess(capital['final'],500)
        self.assertAlmostEqual(trades[0]['netPct'],-.24)
        self.assertEqual(curve[-1],capital['final'])


if __name__=='__main__':
    unittest.main()
