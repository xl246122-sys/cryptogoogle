import unittest
from test_ai_engine import make_snapshot
from cryptog.ai_policy import trade_plan, same_opportunity, rolling_windows, alert_card

class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = make_snapshot()
        self.decision = dict(scenario='RANGE_SUPPORT_BOUNCE', hold_minutes=60,
            summary_zh='箱体下沿收复', target_tp1=68200., stop_loss=66300.,
            anchor_timeframe='5m', anchor_time_ms=self.snapshot['series']['5m'][-1]['time'])

    def test_module_constraints_and_anchor(self):
        self.assertEqual(trade_plan(self.decision,self.snapshot,67005.)['scenarioNameZh'],'区间震荡')
        for changes in ({'hold_minutes':500},{'summary_zh':'长'*26},{'target_tp1':67300.},
                        {'stop_loss':66990.},{'anchor_time_ms':0},{'scenario':'ORDERBOOK_ABSORPTION'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                trade_plan({**self.decision,**changes},self.snapshot,67005.)

    def test_real_structure_has_no_artificial_minimum_stop_distance(self):
        self.assertEqual(trade_plan({**self.decision,'stop_loss':66900.},self.snapshot,67005.)['structureLow'],66980.)

    def test_structure_dedup_not_time_cooldown(self):
        sig=dict(module='RANGE_SUPPORT_BOUNCE',entryMin=66950,entryMax=67100,entryPrice=67005,structureLow=66980)
        self.assertTrue(same_opportunity(sig,{**sig,'atMs':999999999}))
        self.assertFalse(same_opportunity(sig,{**sig,'entryMin':68000,'entryMax':68100}))

    def test_missing_window_never_fabricated(self):
        self.assertFalse(rolling_windows(self.snapshot)['240']['available'])

    def test_card_has_exact_six_fields(self):
        sig=dict(atMs=0,scenarioNameZh='区间震荡',entryMin=100,entryMax=101,summaryZh='下沿收复',
                 targetTP1=103, grossProfitPercent1=3,profitPercent1=2.89,stopLoss=99,stopLossPercent=1,timeHorizon='60分钟')
        self.assertEqual(len(alert_card(sig).splitlines()),6)

if __name__ == '__main__':
    unittest.main()
