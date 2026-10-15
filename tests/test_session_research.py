import unittest
from datetime import datetime
from cryptog.session_research import session_context,shock_measure
class SessionTests(unittest.TestCase):
 def label(self,text):return session_context(int(datetime.fromisoformat(text).timestamp()*1000))
 def test_dst_and_open(self):
  self.assertEqual(self.label('2026-10-15T21:30:00+08:00')['label'],'OPEN_WINDOW')
  self.assertEqual(self.label('2026-11-02T22:30:00+08:00')['label'],'OPEN_WINDOW')
  self.assertEqual(self.label('2026-10-15T21:29:00+08:00')['label'],'PRE_OPEN')
 def test_holiday_weekend_early_unknown(self):
  self.assertEqual(self.label('2026-11-26T10:00:00-05:00')['label'],'HOLIDAY')
  self.assertEqual(self.label('2026-11-27T13:00:00-05:00')['label'],'POST_CLOSE')
  self.assertEqual(self.label('2026-10-17T10:00:00-04:00')['label'],'WEEKEND')
  self.assertEqual(self.label('2027-01-04T10:00:00-05:00')['label'],'UNKNOWN')
 def test_shock_order_and_recovery_excluded(self):
  bars=[dict(high=100,low=100,close=100,close_time=i) for i in range(10)]
  bars[-5]['low']=98;bars[-5]['high']=99
  self.assertEqual(shock_measure(bars,3)['dropPct'],2)
  self.assertTrue(shock_measure(bars,3)['reclaim'])
  bars[-1]['low']=80
  self.assertEqual(shock_measure(bars,3)['dropPct'],2)
if __name__=='__main__':unittest.main()
