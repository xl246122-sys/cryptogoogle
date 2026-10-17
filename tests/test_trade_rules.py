import copy
import json
import tempfile
import unittest
from unittest.mock import patch
from offline_daemon import daemon as m
from cryptog import strategy as strategy_module
import test_signal_validity as signal_tests


class TradeRuleTests(unittest.TestCase):
    def fixture(self):
        f = signal_tests.SignalValidityTests()
        f.setUp()
        return f

    def track(self, model='BREAKOUT', start=1000000):
        policy = m.TRADE_POLICIES[model]
        return dict(entry=100., tp1=102., tp2=104., sl=99., invalidationPrice=99.5,
                    alertedAtMs=start, lastSeenMs=start, lastPrice=100., maxHigh=100., minLow=100.,
                    deadlineMs=start+policy['max_hold_minutes']*60000, tp1Fraction=policy['tp1_fraction'],
                    remainingFraction=1., exitLegs=[], firstTp1Ms=None, firstTp2Ms=None, firstSlMs=None)

    def test_three_policies_are_independent(self):
        self.assertEqual(set(m.TRADE_POLICIES), {'BREAKOUT', 'REBOUND', 'RANGE'})
        self.assertEqual([m.TRADE_POLICIES[k]['max_hold_minutes'] for k in ('BREAKOUT','REBOUND','RANGE')], [240,90,240])
        self.assertEqual([m.TRADE_POLICIES[k]['tp1_fraction'] for k in ('BREAKOUT','REBOUND','RANGE')], [.5,.7,1.])

    def test_nearest_barrier_cannot_be_skipped_or_replaced_with_atr(self):
        for model in m.TRADE_POLICIES:
            self.assertIsNone(m.model_targets(model, 100., 99.5, [100.4, 108.]))
            self.assertIsNone(m.model_targets(model, 100., 99.5, []))

    def test_uniform_gross_floor_does_not_inflate_targets(self):
        for model in m.TRADE_POLICIES:
            self.assertIsNotNone(m.model_targets(model,100.,99.8,[101.]))
            self.assertIsNone(m.model_targets(model,100.,99.8,[100.7]))
        target = m.model_targets('RANGE',100.,99.8,[102.])
        self.assertIsNotNone(target)
        self.assertLess(target['target_tp1'],102.)
        self.assertGreaterEqual(target['net_tp1'],.59)

    def test_caps_only_lower_targets_and_no_stop_compression(self):
        for model, cap in [('RANGE',4.), ('REBOUND',6.)]:
            target = m.model_targets(model,100.,99.5,[110.,120.])
            self.assertLessEqual(target['net_tp2'],cap)
            self.assertEqual(target['tp1_fraction'],1.)
        self.assertIsNone(m.model_targets('RANGE',100.,97.,[110.]))
        self.assertIsNone(m.model_targets('BREAKOUT',100.,98.,[110.]))

    def test_real_breakout_scan_stores_rules_and_uses_observed_resistance(self):
        f = self.fixture()
        signal = f.scan()
        self.assertIsNotNone(signal)
        self.assertEqual(signal['model'],'BREAKOUT')
        self.assertEqual(signal['max_hold_minutes'],240)
        self.assertLess(signal['target_tp1'],103.)
        rules = json.loads(m.fcm_payload(signal)['tradeRules'])
        self.assertEqual(rules['invalidationPrice'],100.6)
        self.assertEqual(rules['tp1Fraction'],.5)

    def test_live_scan_no_atr_fallback(self):
        f = self.fixture()
        with patch.object(strategy_module,'observed_resistances',return_value=[100.7,110.]):
            self.assertIsNone(f.scan())

    def test_rebound_requires_fast_crash_not_just_daily_decline(self):
        f = self.fixture()
        self.assertFalse(m.recent_crash_confirmed(f.five))
        for c in f.five[-12:-4]: c['high'] = 105.
        self.assertTrue(m.recent_crash_confirmed(f.five))

    def test_stable_box_and_trend_rejection(self):
        f = self.fixture()
        bars = copy.deepcopy(f.regime)
        for i,c in enumerate(bars):
            p = 100.2 + (4-abs(i%8-4))*.9
            c.update(open=p-.05,close=p,low=p-.2,high=p+.2)
        self.assertIsNotNone(m.stable_range_box(bars,100.3))
        self.assertIsNone(m.stable_range_box(bars,103.5))
        for i,c in enumerate(bars): c.update(open=100+i*.1,close=100+i*.1,low=99.9+i*.1,high=100.1+i*.1)
        self.assertIsNone(m.stable_range_box(bars,100.3))

    def test_range_routing_uses_box_and_reversal_and_nearest_obstacle(self):
        f = self.fixture()
        f.ticker['price'] = 100.3
        f.macro.update(trend='RANGING')
        # Isolate route selection and target binding from separately tested reversal math.
        with patch.object(strategy_module,'_closed_breakout',return_value=None), patch.object(strategy_module,'stable_range_box',return_value={'low':100.,'mid':102.,'high':104.}), patch.object(strategy_module,'verify_micro_range_reversal',return_value=(True,'ok',100.,104.)), patch.object(m.TechnicalIndicators,'rsi',return_value=40.):
            signal = f.scan()
            self.assertIsNotNone(signal)
            self.assertEqual(signal['model'],'RANGE')
            self.assertEqual(signal['tp1_fraction'],1.)
            with patch.object(strategy_module,'verify_micro_range_reversal',return_value=(False,'knife',100.,104.)):
                self.assertIsNone(f.scan())
            with patch.object(strategy_module,'observed_resistances',return_value=[100.6,104.]):
                self.assertIsNone(f.scan())

    def test_rebound_routing_preserves_independent_rule(self):
        f = self.fixture()
        f.ticker.update(price=100.3,change24h=-6.,high24h=107.)
        f.macro.update(trend='BEARISH',is_bearish=True)
        with patch.object(strategy_module,'_closed_breakout',return_value=None), patch.object(strategy_module,'recent_crash_confirmed',return_value=True), patch.object(strategy_module,'verify_micro_range_reversal',return_value=(True,'ok',100.,104.)), patch.object(m.TechnicalIndicators,'rsi',return_value=40.), patch.object(m.TechnicalIndicators,'vwap_and_bands',return_value=(102.,1.,104.,98.,102.)):
            signal=f.scan()
            self.assertIsNotNone(signal)
            self.assertEqual(signal['model'],'REBOUND')
            self.assertEqual(signal['max_hold_minutes'],90)
            self.assertEqual(signal['tp1_fraction'],.7)
            with patch.object(strategy_module,'recent_crash_confirmed',return_value=False): self.assertIsNone(f.scan())

    def test_partial_then_invalidation_does_not_move_stop(self):
        t=self.track()
        self.assertIsNone(m._advance_rule_track(t,102.,1001000))
        self.assertEqual(t['remainingFraction'],.5)
        self.assertEqual(t['sl'],99.)
        self.assertEqual(m._advance_rule_track(t,99.4,1002000),'INVALIDATION_EXIT')
        self.assertEqual(t['remainingFraction'],0.)
        self.assertAlmostEqual(t['referenceNetPct'],.59,places=4)

    def test_range_tp1_closes_all_and_rebound_tp1_closes_seventy_percent(self):
        t=self.track('RANGE')
        self.assertEqual(m._advance_rule_track(t,102.,1001000),'TP1_EXIT')
        self.assertEqual(t['remainingFraction'],0.)
        t=self.track('REBOUND')
        self.assertIsNone(m._advance_rule_track(t,102.,1001000))
        self.assertAlmostEqual(t['remainingFraction'],.3)
        self.assertEqual(m._advance_rule_track(t,104.,1002000),'TP2_EXIT')

    def test_stop_before_ten_minutes_is_not_blocked(self):
        t=self.track('RANGE')
        self.assertEqual(m._advance_rule_track(t,98.8,1001000),'STOP_EXIT')
        self.assertAlmostEqual(t['referenceNetPct'],-1.31)

    def test_deadline_precedes_tp_even_at_exact_boundary(self):
        t=self.track()
        self.assertEqual(m._advance_rule_track(t,105.,t['deadlineMs']),'TIME_EXIT')
        self.assertIsNone(t['firstTp1Ms'])
        self.assertEqual(t['maxHigh'],100.)

    def test_late_quote_cannot_turn_timeout_into_profit(self):
        t=self.track()
        self.assertEqual(m._advance_rule_track(t,110.,t['deadlineMs']+1),'TIME_EXIT_PRICE_UNAVAILABLE')
        self.assertIsNone(t['referenceNetPct'])
        self.assertIsNone(t['firstTp1Ms'])
        self.assertEqual(t['maxHigh'],100.)

    def test_offline_deadline_and_duplicate_updates(self):
        m.set_library_dir(tempfile.mkdtemp(prefix='cg-step2-'))
        f=self.fixture(); sig=f.scan(); self.assertIsNotNone(sig)
        aid=m.record_model_alert(sig)
        deadline=sig['timestamp']+sig['max_hold_minutes']*60000
        m.observe_model_price(0,deadline+1)
        state=m.read_track_status(aid)
        self.assertEqual(state['pathStatus'],'TIME_EXIT_PRICE_UNAVAILABLE')
        self.assertTrue(state['outcomeWritten'])
        m.observe_model_price(200.,deadline+10000)
        self.assertEqual(m.read_track_status(aid)['maxHigh'],sig['entry_price'])

if __name__ == '__main__': unittest.main()
