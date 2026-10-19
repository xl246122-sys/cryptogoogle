import math
import os
import tempfile
import unittest

from cryptog.evolution import Pipeline, stage_review
from cryptog.ledger import Ledger
from cryptog.config import V2_SHADOW_MS, V2_TRIAL_MS
from cryptog.validation import promotion_decision
from cryptog.research_protocol import register_trial, trial_inventory, whole_trade_metrics, block_bootstrap_lower
from cryptog.diagnostic_replay import scenario_entry

T0 = 1700000000000
GOOD = dict(trades=80, expectancyPct=.2, bootstrapLower95=.05, winRate=.6,
            profitFactor=1.4, perDay=1.2, dsr=.99)


class StageDTests(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix='.sqlite3')
        os.close(fd)
        self.ledger = Ledger(self.path)
        self.pipe = Pipeline(self.ledger)

    def tearDown(self):
        self.ledger.close()
        os.remove(self.path)

    def test_scans_do_not_inflate_unique_candidates_even_after_restart(self):
        self.pipe.consider('S1', GOOD, T0, pbo_value=.1)
        for i in range(100):
            self.pipe.note('S1', T0+i, 'same-candidate')
        Pipeline(self.ledger).note('S1', T0+101, 'same-candidate')
        self.pipe.note('S1', T0+102)
        self.assertEqual(self.pipe._row('S1')['records'], 1)
        self.pipe.note('S1', T0+103, 'another-candidate')
        self.assertEqual(self.pipe._row('S1')['records'], 2)

    def test_clock_and_candidate_count_cannot_promote(self):
        self.pipe.consider('S1', GOOD, T0, pbo_value=.1)
        self.pipe.note('S1', T0, 'candidate')
        result = self.pipe.tick('S1', T0+V2_SHADOW_MS)
        self.assertFalse(result['changed'])
        self.assertEqual(result['stage'], 'SHADOW')
        self.assertTrue(result['review']['gaps'])
        self.assertEqual(self.ledger.counts()['promotions'], 0)

    def test_empty_trial_cannot_become_live(self):
        with self.ledger.store.db:
            self.pipe._save('S2', 'TRIAL', T0, 100, {})
        self.assertFalse(self.pipe.tick('S2', T0+V2_TRIAL_MS)['changed'])
        self.assertEqual(self.pipe.stage_of('S2'), 'TRIAL')

    def test_uncertain_and_duplicate_trades_fail_closed(self):
        trade = dict(candidateId='a', openedMs=T0+1, closedMs=T0+60000,
                     netPct=.8, eligibleForValidation=True)
        report = stage_review('S1', 'SHADOW', T0, T0+V2_SHADOW_MS,
                              [trade, trade, dict(trade, candidateId='b', eligibleForValidation=False)], {})
        self.assertFalse(report['passes'])
        self.assertEqual(report['summary']['trades'], 1)

    def test_nonfinite_metrics_never_pass(self):
        for field in ('expectancyPct', 'bootstrapLower95', 'winRate', 'profitFactor', 'perDay', 'dsr'):
            self.assertFalse(promotion_decision(dict(GOOD, **{field: math.nan}), 21, .1)['passes'], field)
        self.assertFalse(promotion_decision(GOOD, 1, math.nan)['passes'])

    def test_trial_registration_is_append_only_and_missing_history_stays_unknown(self):
        with tempfile.TemporaryDirectory() as folder:
            register_trial(folder, 'failed-run', 'hash', {'frictionPct': .24}, T0)
            with self.assertRaises(FileExistsError):
                register_trial(folder, 'failed-run', 'hash', {}, T0)
            inventory = trial_inventory(folder)
            self.assertEqual(inventory['registered'], 1)
            self.assertIsNone(inventory['nTrials'])
            self.assertFalse(inventory['complete'])

    def test_whole_trade_rate_includes_losses_and_exposes_exclusions(self):
        rows = [dict(netPct=v, openedMs=T0+i*86400000, closedMs=T0+i*86400000+60000,
                     eligibleForValidation=True) for i, v in enumerate([.8, -.5, 0, .4])]
        rows.append(dict(rows[0], netPct=1.5, eligibleForValidation=False))
        metrics = whole_trade_metrics(rows)
        self.assertEqual(metrics['achievementRate'], .25)
        self.assertEqual(metrics['excluded'], 1)
        self.assertIsNotNone(metrics['blockBootstrapLower95'])
        self.assertIsNone(block_bootstrap_lower([rows[0]]))

    def test_delivery_delay_escape_voids_order_and_touch_is_not_a_fill(self):
        signal = dict(entry_min=99.9, entry_max=100.1, stop_loss=99, expires_at=T0+600000)
        later = dict(time=T0+60000, open=100, high=100.1, low=99.95)
        escaped = dict(time=T0, open=100, high=101, low=100)
        self.assertIsNone(scenario_entry(signal, [escaped, later], T0+60000))
        touch = dict(time=T0+60000, open=100.2, high=100.2, low=100)
        self.assertIsNone(scenario_entry(signal, [touch], T0+60000))
        self.assertEqual(scenario_entry(signal, [later], T0+60000), later)


if __name__ == '__main__':
    unittest.main()
