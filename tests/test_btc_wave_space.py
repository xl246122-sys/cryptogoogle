"""Boundary and causality checks for the descriptive study, no live data needed."""
import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from report_btc_wave_space import audit, confirm, event_starts, path_stats


class WaveStudyTests(unittest.TestCase):
    def test_events_require_five_full_quiet_minutes(self):
        mask=np.zeros(20,dtype=bool)
        mask[[0,1,6,12]]=True
        self.assertEqual(event_starts(mask).tolist(),[0,12])
        self.assertEqual(event_starts(np.zeros(4,dtype=bool)).tolist(),[])

    def test_confirmation_uses_close_and_only_known_previous_high(self):
        bars=np.array([[100,102,98,99],[99,101,98,100],[100,104,99,103],[103,999,1,500]],dtype=float)
        self.assertEqual(confirm(bars,0),2)
        self.assertEqual(confirm(bars[:3],0),2)
        self.assertIsNone(confirm(bars[:2],0))

    def test_confirmation_timeout(self):
        bars=np.tile([100,101,99,100],(33,1)).astype(float)
        bars[31]=[100,103,99,102]
        self.assertIsNone(confirm(bars,0))

    def test_outcomes_exclude_pre_entry_and_censor_incomplete_horizon(self):
        bars=np.array([[100,999,1,100],[100,102,99,101],[101,103,98,102]],dtype=float)
        mfe,mae,end=path_stats(bars,1,2,100)
        self.assertAlmostEqual(mfe,3)
        self.assertAlmostEqual(mae,-2)
        self.assertAlmostEqual(end,2)
        self.assertIsNone(path_stats(bars,1,3,100))

    def test_missing_and_invalid_data_rejected(self):
        p=dict(startInclusiveMs=0,endExclusiveMs=60000,sampleStartMs=0)
        frame=pd.DataFrame([[0,100,101,99,100,1,59999,.5]],columns=['time','open','high','low','close','volume','close_time','taker_buy_base'])
        with self.assertRaisesRegex(ValueError,'missing'):
            audit(frame,p|dict(endExclusiveMs=120000))
        frame.loc[0,'high']=98
        with self.assertRaisesRegex(ValueError,'Invalid'):
            audit(frame,p)


if __name__=='__main__':
    unittest.main()
