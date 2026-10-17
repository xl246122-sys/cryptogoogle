import copy
import threading
import unittest
from unittest.mock import patch
from test_ai_engine import AIEngineTests, NOW
from cryptog.ai_policy import target_evidence
from cryptog.ai_engine import AIDeliveryWorker


class DeliveryContractTests(AIEngineTests):
    def decision(self):
        return dict(entry_min=66950,entry_max=67100,target_tp1=68200,
                    stop_loss=66300,scenario='RANGE_SUPPORT_BOUNCE',summary_zh='支撑收复',
                    hold_minutes=60,anchor_timeframe='5m',
                    anchor_time_ms=self.snapshot['series']['5m'][-1]['time'])

    def enqueue(self):
        self.assertTrue(self.ai.verify_and_push_signal({'provider':'GEMINI','model':'mock'},self.decision(),NOW))

    def dispatch(self, delta=0):
        with patch('cryptog.ai_engine.time.time',return_value=(NOW+delta)/1000):
            self.ai.dispatch_pending()

    def test_missing_or_nearer_resistance_rejects_target(self):
        flat=copy.deepcopy(self.snapshot)
        flat['series']['5m'][-4]['high']=67020
        with self.assertRaisesRegex(ValueError,'NO_CONFIRMED'):
            target_evidence(flat,67005,69000,69000)
        with self.assertRaisesRegex(ValueError,'CROSSES'):
            target_evidence(self.snapshot,67005,69000,69000)
        self.snapshot['series']['5m'][-8]['high']=67500
        with self.assertRaisesRegex(ValueError,'CROSSES'):
            target_evidence(self.snapshot,67005,68200,68200)

    def test_forming_and_gapped_anchor_are_not_evidence(self):
        self.snapshot['series']['5m'][-3]['is_closed']=False
        with self.assertRaises(ValueError):
            target_evidence(self.snapshot,67005,68200,68200)
        self.snapshot['series']['5m'][-3]['is_closed']=True
        self.snapshot['series']['5m'][-3]['time']+=1
        with self.assertRaises(ValueError):
            target_evidence(self.snapshot,67005,68200,68200)

    def test_failure_backoff_and_success_are_durable(self):
        self.enqueue()
        calls=[]
        self.ai.send_fcm_alert=lambda *args: calls.append(args) or len(calls)>1
        self.dispatch()
        self.dispatch(1000)
        self.assertEqual(len(calls),1)
        self.dispatch(5000)
        self.dispatch(6000)
        self.assertEqual(len(calls),2)
        self.assertEqual(calls[0][2]['eventId'],calls[1][2]['eventId'])
        self.assertEqual(self.store.db.execute('SELECT attempts,last_error,accepted_ms FROM ai_delivery').fetchone(),(2,None,NOW+5000))
        self.assertEqual(self.store.db.execute('SELECT state FROM ai_signals').fetchone()[0],'FCM_ACCEPTED')

    def test_disabled_pending_cancelled_and_not_resurrected(self):
        self.enqueue()
        self.ai.set_config({'enabled':False})
        self.dispatch()
        with patch('cryptog.ai_engine.time.time',return_value=NOW/1000):
            self.ai.track_plans()
        self.assertFalse(self.ai.active_signals)
        self.assertEqual(self.fcm_calls,[])
        self.assertEqual(self.store.db.execute('SELECT state FROM ai_signals').fetchone()[0],'CANCELLED')

    def test_delivery_does_not_wait_for_analysis_lock(self):
        self.enqueue()
        self.ai.lock.acquire()
        try:
            self.dispatch()
        finally:
            self.ai.lock.release()
        self.assertEqual(len(self.fcm_calls),1)

    def test_completed_plan_removed_from_active(self):
        self.enqueue()
        self.cache.snap['ticker']['bid_price']=69000
        with patch('cryptog.ai_engine.time.time',return_value=NOW/1000):
            self.ai.track_plans()
        self.assertFalse(self.ai.active_signals)


if __name__=='__main__': unittest.main()
