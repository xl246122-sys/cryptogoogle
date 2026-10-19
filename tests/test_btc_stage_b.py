import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from research_btc_stage_b import past_quantile, confirmation, exit_signal, settle_exit, paired_exits, simulate_group, execution_audit, build_features, DAY
from research_btc_dynamic import simulate


def fixture(n=40):
    bars=np.tile([100.,101.,99.,100.],(n,1))
    return dict(bars=bars,rsi=np.full(n,50.),atr=np.ones(n),x=np.zeros(n,dtype=bool),
        pivots=np.full(n,-1),lastPivot=np.full(n,-1),rsiRise=np.ones(n,dtype=bool),
        lowRise=np.ones(n,dtype=bool),sellRatio2=np.full(n,.4),sellRatio3=np.full(n,.6),
        levels={'rsi10':np.full(n,30.),'rsi90':np.full(n,70.)})


class StageBTests(unittest.TestCase):
    def test_threshold_excludes_current_future_and_positive_samples(self):
        a=np.array([-4.,-2.,1.,3.,-1.,99.])
        v=past_quantile(a,5,.95,True,5)
        a[5]=-999
        self.assertEqual(v,past_quantile(a,5,.95,True,5))
        self.assertAlmostEqual(v,3.8)

    def test_c1_requires_later_confirmation_and_revokes_on_new_low(self):
        f=fixture();f['x'][2]=True;f['bars'][2]=[100,103,99,102]
        f['bars'][3]=[98,100,97,99]  # breaks observed floor; not green breakout
        f['bars'][4]=[100,103,99,102]  # C0 alone after revoke is insufficient
        j,log=confirmation(f,0,'C1')
        self.assertIsNone(j)
        self.assertTrue(any(x[2]=='X1_LOW_BROKEN' for x in log))
        f['x'][5]=True;f['bars'][6]=[100,103,99,102]
        self.assertEqual(confirmation(f,0,'C1')[0],6)

    def test_c2_pivot_not_available_before_two_right_bars(self):
        f=fixture();f['bars'][:,2]=98;f['bars'][1,2]=95
        f['pivots'][3]=1;f['lastPivot'][3:]=1
        f['bars'][3,2]=96;f['x'][4]=True;f['bars'][7,2]=97
        f['pivots'][9]=7;f['lastPivot'][9:]=7
        f['bars'][8,3]=102;f['bars'][9,3]=102
        self.assertEqual(confirmation(f,3,'C2')[0],9)
        f['bars'][10:]=10000  # future cannot move earlier confirmation
        self.assertEqual(confirmation(f,3,'C2')[0],9)

    def test_overbought_before_entry_is_not_holding_evidence(self):
        f=fixture();f['rsi'][2]=99;f['rsi'][3:6]=[65,60,55]
        f['bars'][5,3]=98
        self.assertFalse(exit_signal(f,3,5,'E1'))
        f['rsi'][3]=80
        self.assertTrue(exit_signal(f,3,5,'E1'))

    def test_exit_delay_and_protection_priority(self):
        f=fixture(10)
        with patch('research_btc_stage_b.exit_signal',side_effect=lambda f,k,j,m:j==2):
            self.assertEqual(settle_exit(f,0,8,98,105,'E1',1),(4,100.,'EXHAUSTION_EXIT',2))
            f['bars'][3,2]=97
            self.assertEqual(settle_exit(f,0,8,98,105,'E1',1),(3,98.,'STOP',2))
            f['bars'][3,2]=99;f['bars'][4]=[97,103,96,100]
            self.assertEqual(settle_exit(f,0,8,98,105,'E1',1),(4,97.,'STOP_GAP',2))

    def test_due_open_exit_does_not_use_later_intrabar_stop(self):
        f=fixture(10);f['bars'][4,2]=90
        with patch('research_btc_stage_b.exit_signal',side_effect=lambda f,k,j,m:j==2):
            self.assertEqual(settle_exit(f,0,8,98,105,'E2',1),(4,100.,'EXHAUSTION_EXIT',2))
        self.assertIsNone(settle_exit(f,8,5,98,105,'E2',1))

    def test_no_reminder_exit_reproduces_account(self):
        f=fixture(20);f['bars'][:]=[100,100.1,99.9,100]
        df=pd.DataFrame(f['bars'],columns=['open','high','low','close']);df['time']=np.arange(20)*60000
        p=dict(method='TEST',windowMin=5,triggerIndex=0,parentIndex=0,confirmIndex=0,
            entryLow=99.9,entryHigh=100.1,stop=99.5,target=101.2,holdMinutes=5,minNet=.8)
        a=simulate(df,[p],0,.24,1);b=simulate_group(df,[p],0,.24,1,f,'E1')
        self.assertAlmostEqual(a[2]['final'],b[2]['final'])
        np.testing.assert_allclose(a[3],b[3])
        self.assertEqual(a[0][0]['closedMs'],b[0][0]['closedMs'])

    def test_pair_keeps_entry_notional_and_no_added_entries(self):
        f=fixture(40);df=pd.DataFrame({'time':np.arange(40)*60000})
        t=dict(openedMs=0,windowMin=5,stop=98,target=105,entry=100.,parentIndex=0,notional=123.,netPct=-.24)
        with patch('research_btc_stage_b.exit_signal',side_effect=lambda f,k,j,m:j==2):
            rows=paired_exits(df,f,[t],.24,1,'E2')
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['notional'],123.)
        self.assertEqual(rows[0]['entry'],100.);self.assertEqual(rows[0]['openedMs'],0)

    def test_feature_prefix_independent_of_future(self):
        n=91*DAY+12;start=91*DAY;prices=100+np.sin(np.arange(n)/20)
        df=pd.DataFrame(dict(time=np.arange(n)*60000,open=prices,close=prices,
            high=prices+.1,low=prices-.1,volume=np.ones(n),taker_buy_base=np.full(n,.4)))
        a,_=build_features(df,start)
        df.loc[start+6:,['open','close','high','low']]*=2
        b,_=build_features(df,start)
        for key in ['rsi','x','pivots']:
            np.testing.assert_equal(a[key][:start+6],b[key][:start+6])
        for key in a['levels']: np.testing.assert_equal(a['levels'][key],b['levels'][key])

    def test_position_reminder_cannot_claim_profit_when_net_negative(self):
        f=fixture(12);df=pd.DataFrame({'time':np.arange(12)*60000})
        p=dict(method='B-R05',windowMin=5,triggerIndex=0,parentIndex=0,confirmIndex=0,
            confirmMs=60000,entryLow=99.9,entryHigh=100.1,stop=98,target=105,minNet=.8)
        t=dict(openedMs=120000,windowMin=5,parentIndex=0,entry=100,notional=100,
            reminderMs=300000,holdMinutes=5,outcome='EXHAUSTION_EXIT',exit=100,executionMs=360000)
        _,events=execution_audit(df,f,[p],[t],.24,1,'B-R05')
        reminder=[e for e in events if e['phase']=='OBSERVED_HOLDING_EXHAUSTION'][0]
        self.assertIn('风险退出提醒',reminder['evidence'])
        self.assertEqual(events[-1]['remainingQuantity'],0)
        self.assertEqual(events[-1]['positionVersion'],2)
        self.assertEqual(execution_audit(df,f,[p],[],.24,1,'B-R05')[1],[])


if __name__=='__main__': unittest.main()
