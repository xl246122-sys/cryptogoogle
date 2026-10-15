import copy
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from offline_daemon import daemon as m


class ExecutionRecordsTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.mkdtemp(prefix='cryptog-records-')
        m.set_library_dir(self.directory)
        self.now = int(time.time()*1000)-100000

    def fill(self, id='buy', side='BUY', **updates):
        return dict(fillId=id, positionId='position-1', source='MANUAL', side=side,
                    price=100. if side=='BUY' else 110., quantity=1., executedAtMs=self.now+(0 if side=='BUY' else 1000),
                    commission=.1, commissionAsset='USDT', commissionAssetUsdtRate=None,
                    referencePrice=None, referenceAtMs=None, timeApproximate=False, **{}) | updates

    def action(self, fill, **updates):
        return dict(eventId=fill['fillId'], recordType='MANUAL_FILL', alertId='manual-position-1', actedAtMs=self.now+2000, fill=fill) | updates

    def rows(self, name='user_actions'):
        return [json.loads(line) for line in Path(self.directory,f'{name}.jsonl').read_text(encoding='utf-8').splitlines()]

    def test_partial_exit_allocates_buy_cost_and_each_sell_fee(self):
        out=m.execution_summary([self.fill(),self.fill('sell','SELL',quantity=.4,commission=.044)])
        self.assertAlmostEqual(out['realizedNetUsdt'],3.916)
        self.assertAlmostEqual(out['remainingCostUsdt'],60.06)
        self.assertAlmostEqual(out['inventory'],.6)
        self.assertFalse(out['closed'])

    def test_btc_buy_fee_reduces_inventory_without_double_deduction(self):
        out=m.execution_summary([self.fill(commission=.001,commissionAsset='BTC'), self.fill('sell','SELL',quantity=.999,commission=.10989)])
        self.assertTrue(out['closed'])
        self.assertAlmostEqual(out['realizedNetUsdt'],9.78011)

    def test_btc_sell_fee_consumes_extra_inventory(self):
        out=m.execution_summary([self.fill(commission=0),self.fill('sell','SELL',quantity=.99,commission=.01,commissionAsset='BTC')])
        self.assertTrue(out['closed']); self.assertAlmostEqual(out['realizedNetUsdt'],8.9)

    def test_bnb_conversion_unknown_and_zero_are_distinct(self):
        for changes in [dict(commission=None),dict(commissionAsset='BNB')]:
            out=m.execution_summary([self.fill(**changes),self.fill('s','SELL')])
            self.assertIsNone(out['realizedNetUsdt']); self.assertIsNone(out['feeUsdt'])
        out=m.execution_summary([self.fill(commission=.001,commissionAsset='BNB',commissionAssetUsdtRate=600),self.fill('s','SELL',commission=0)])
        self.assertAlmostEqual(out['realizedNetUsdt'],9.4)

    def test_slippage_is_diagnostic_not_double_deducted(self):
        out=m.execution_summary([self.fill(referencePrice=99.,referenceAtMs=self.now-5000), self.fill('s','SELL')])
        self.assertAlmostEqual(out['realizedNetUsdt'],9.8)
        self.assertEqual(out['slippage'][0]['quoteDifferenceUsdt'],1)
        self.assertEqual(out['slippage'][0]['benchmarkAgeMs'],5000)

    def test_invalid_inputs_and_oversell_never_append(self):
        for fill in [self.fill(price=float('nan')),self.fill(quantity=-1),self.fill(commission=-1),self.fill(executedAtMs=int(time.time()*1000)+60000),self.fill('s','SELL'),self.fill(referencePrice=100.,referenceAtMs=None)]:
            self.assertFalse(m.apply_user_action(self.action(fill))['ok'])
        self.assertFalse(Path(self.directory,'user_actions.jsonl').exists())

    def test_lost_ack_retry_and_restart_append_once(self):
        a=self.action(self.fill())
        self.assertTrue(m.apply_user_action(a)['ok'])
        m.set_library_dir(self.directory)
        response=m.apply_user_action(a)
        self.assertTrue(response['duplicate']); self.assertEqual(response['eventId'],'buy')
        self.assertEqual(len(self.rows()),1)
        altered=copy.deepcopy(a);altered['fill']['price']=101
        self.assertFalse(m.apply_user_action(altered)['ok'])

    def test_fill_identity_dedupes_across_event_ids(self):
        self.assertTrue(m.apply_user_action(self.action(self.fill()))['ok'])
        self.assertFalse(m.apply_user_action(self.action(self.fill(),eventId='other'))['ok'])
        self.assertEqual(len(self.rows()),1)

    def test_exchange_trade_id_blocks_manual_duplicate_but_allows_correction(self):
        m.apply_user_action(self.action(self.fill(exchangeTradeId='12345')))
        self.assertFalse(m.apply_user_action(self.action(self.fill('duplicate',exchangeTradeId='12345')))['ok'])
        self.assertTrue(m.apply_user_action(self.action(self.fill('corrected',exchangeTradeId='12345',price=101),replacesEventId='buy'))['ok'])

    def test_crash_after_append_before_projection_is_recovered(self):
        with patch.object(m,'_save_open_tracks',side_effect=OSError('disk failure')):
            with self.assertRaises(OSError):m.apply_user_action(self.action(self.fill()))
        m.set_library_dir(self.directory)
        self.assertTrue(m.apply_user_action(self.action(self.fill()))['duplicate'])
        self.assertEqual(len(self.rows()),1)

    def test_partial_tail_preserved_and_valid_history_replayed(self):
        m.apply_user_action(self.action(self.fill()))
        with Path(self.directory,'user_actions.jsonl').open('ab') as f:f.write(b'{"eventId":')
        m.set_library_dir(self.directory)
        self.assertTrue(m.apply_user_action(self.action(self.fill('s','SELL')))['ok'])
        self.assertEqual(len(self.rows()),2)
        self.assertEqual(len(list(Path(self.directory).glob('*.partial.*'))),1)

    def test_middle_corruption_stops_writes(self):
        Path(self.directory,'user_actions.jsonl').write_text('invalid\n',encoding='utf-8')
        self.assertFalse(m.apply_user_action(self.action(self.fill()))['ok'])
        self.assertFalse(m._LIBRARY_READY)

    def test_correction_keeps_original_and_recalculates(self):
        m.apply_user_action(self.action(self.fill()))
        m.apply_user_action(self.action(self.fill('s','SELL')))
        fixed=self.fill('fixed',price=102.)
        self.assertTrue(m.apply_user_action(self.action(fixed,replacesEventId='buy'))['ok'])
        self.assertEqual(len(self.rows()),3)
        self.assertAlmostEqual(self.rows()[-1]['executionSummary']['realizedNetUsdt'],7.8)
        self.assertFalse(m.apply_user_action(self.action(self.fill('fixed2'),replacesEventId='buy'))['ok'])

    def test_approximate_timestamp_never_claims_precise_latency(self):
        m.apply_user_action(self.action(self.fill(timeApproximate=True),signalAtMs=self.now-5000))
        self.assertIsNone(self.rows()[-1]['entryLatency']['signalToEntryMs'])

    def test_alert_snapshot_recovers_if_checkpoint_was_not_saved(self):
        sig=dict(symbol='BTCUSDT',strategy='BURST_BREAKOUT',confirmation_time=self.now-1,timestamp=self.now,entry_price=100,target_tp1=102,target_tp2=104,stop_loss=99)
        with patch.object(m,'_save_open_tracks',side_effect=OSError('disk failure')):
            with self.assertRaises(OSError):m.record_model_alert(sig)
        m.set_library_dir(self.directory)
        aid=m.record_model_alert(sig)
        self.assertEqual(len(self.rows('alerts')),1)
        self.assertEqual(m.OPEN_TRACKS[aid]['signalSnapshot'],sig)

    def test_late_receipt_is_included_in_current_execution_report(self):
        m.apply_user_action(self.action(self.fill(),signalAtMs=self.now-5000))
        self.assertIsNone(self.rows()[-1]['entryLatency']['receivedToEntryMs'])
        m.apply_user_action(dict(eventId='receipt',recordType='PHONE_RECEIVED',alertId='manual-position-1',actedAtMs=self.now-2000))
        self.assertEqual(m.execution_reports('manual-position-1')[0]['entryLatency']['receivedToEntryMs'],2000)

    def test_outcome_append_survives_restart_without_duplicate(self):
        sig=dict(symbol='BTCUSDT',strategy='BURST_BREAKOUT',confirmation_time=self.now-1,timestamp=self.now,entry_price=100,target_tp1=102,target_tp2=104,stop_loss=99)
        aid=m.record_model_alert(sig)
        with patch.object(m,'_save_open_tracks',side_effect=OSError('checkpoint failed')):
            with self.assertRaises(OSError):m.observe_model_price(100,self.now+m.LIBRARY_HORIZON_MS+1)
        m.set_library_dir(self.directory)
        m.observe_model_price(110,self.now+m.LIBRARY_HORIZON_MS+2000)
        self.assertEqual(len(self.rows('outcomes')),1)
        self.assertTrue(m.read_track_status(aid)['outcomeWritten'])

if __name__=='__main__':unittest.main()
