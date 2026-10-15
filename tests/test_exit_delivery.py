import unittest
import threading
import tempfile
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch
from cryptog.storage import EventStore
from cryptog.exit_delivery import ExitDelivery,ExitWorker
from test_positions import check,fill,NOW

class ExitDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.store=EventStore(':memory:');self.delivery=ExitDelivery(self.store)
        self.notice=self.store.reconcile_positions([check([fill()],97)],NOW)[0]['notice']['id']
        self.delivery.register('device','t'*50,NOW)
    def tearDown(self):self.store.close()
    def test_device_status_is_read_only_and_scoped(self):
        self.assertEqual(self.delivery.device_status('device','t'*50),{'registered':True,'matchesCurrentDevice':True})
        self.assertEqual(self.delivery.device_status('device','x'*50),{'registered':True,'matchesCurrentDevice':False})
        self.assertEqual(self.delivery.device_status('device'),{'registered':True,'matchesCurrentDevice':None})
        self.assertEqual(self.delivery.device_status('other','t'*50),{'registered':False,'matchesCurrentDevice':False})
        with self.assertRaises(ValueError):self.delivery.device_status('device','short')
        self.assertTrue(self.delivery.device_status('device','t'*50)['matchesCurrentDevice'])
    def test_no_buy_cooldown_or_market_gate_and_default_shadow(self):
        sent=[]
        worker=ExitWorker(self.delivery,threading.Event(),lambda token,data:sent.append((token,data)) or True,lambda d:True,lambda:True)
        worker.step(NOW);self.assertEqual(sent,[])
        worker.enabled=True
        with patch('cryptog.exit_delivery.time.time',return_value=NOW/1000):worker.step(NOW)
        self.assertEqual(len(sent),1)
        self.assertEqual(set(sent[0][1]),{'eventType','deliveryId','noticeId','issuedAtMs','expiresAtMs'})
        worker.step(NOW+1);self.assertEqual(len(sent),1)
        self.assertEqual(self.delivery.health()['outbox'],{'FCM_ACCEPTED':1})
    def test_failed_send_retry_and_lease_fencing(self):
        self.delivery.sync(NOW);first=self.delivery.claim(NOW)
        self.assertIsNone(self.delivery.claim(NOW+1))
        second=self.delivery.claim(NOW+180000)
        self.delivery.finish(first,NOW+180001,'FCM_ACCEPTED')
        self.assertEqual(self.delivery.health()['outbox'],{'SENDING':1})
        self.delivery.finish(second,NOW+180002,'PENDING','TEST_FAILURE')
        self.assertIsNone(self.delivery.claim(NOW+180003))
        self.assertIsNotNone(self.delivery.claim(NOW+200003))
    def test_close_cancels_leased_notice_and_late_ack_cannot_resurrect(self):
        self.delivery.sync(NOW);item=self.delivery.claim(NOW)
        self.store.reconcile_positions([check([fill(),fill('s','SELL',1,NOW+1)])],NOW+1000)
        self.delivery.finish(item,NOW+2000,'FCM_ACCEPTED')
        self.assertEqual(self.delivery.health()['outbox'],{'CANCELLED':1})
    def test_token_rotation_revoke_and_rebind(self):
        self.delivery.sync(NOW);first=self.delivery.claim(NOW)
        self.delivery.register('device','n'*50,NOW+1);self.delivery.sync(NOW+1)
        second=self.delivery.claim(NOW+1);self.assertNotEqual(first['id'],second['id'])
        self.delivery.register('device',None,NOW+2);self.assertIsNone(self.delivery.claim(NOW+3))
        self.delivery.register('device','n'*50,NOW+4);self.delivery.sync(NOW+4)
        self.assertNotEqual(self.delivery.claim(NOW+4)['id'],second['id'])
    def test_revoked_credential_and_unhealthy_runtime_never_send(self):
        sent=[]
        worker=ExitWorker(self.delivery,threading.Event(),lambda *a:sent.append(a),lambda d:False,lambda:False,True)
        worker.step(NOW);self.assertEqual(sent,[])
        worker.ready=lambda:True;worker.step(NOW)
        self.assertEqual(sent,[]);self.assertEqual(self.delivery.health()['devices'],0)
    def test_receipts_device_scope_duplicate_and_unknown_delivery(self):
        self.delivery.sync(NOW);item=self.delivery.claim(NOW)
        first=self.delivery.receipt('device',item['id'],'OPENED',NOW,NOW+1)
        self.assertEqual(first,self.delivery.receipt('device',item['id'],'OPENED',NOW+20,NOW+30))
        for device,identity,kind in [('other',item['id'],'OPENED'),('device','missing','OPENED'),('device',item['id'],'SOLD')]:
            with self.assertRaises(ValueError):self.delivery.receipt(device,identity,kind,NOW,NOW)
        self.assertEqual(self.delivery.health()['receipts'],{'OPENED':1})
    def test_token_not_shared_and_repeated_registration_preserves_generation(self):
        with self.assertRaises(ValueError):self.delivery.register('other','t'*50,NOW)
        self.delivery.sync(NOW);first=self.delivery.claim(NOW)
        self.delivery.register('device','t'*50,NOW+1);self.delivery.sync(NOW+1)
        self.assertEqual(self.delivery.health()['outbox'],{'SENDING':1})
        self.assertIsNone(self.delivery.claim(NOW+1))
    def test_restart_keeps_queue_and_receipts(self):
        with tempfile.TemporaryDirectory() as directory:
            path=str(Path(directory)/'events.sqlite3');s=EventStore(path);d=ExitDelivery(s)
            s.reconcile_positions([check([fill()],97)],NOW);d.register('device','t'*50,NOW);d.sync(NOW)
            item=d.claim(NOW);s.close();s=EventStore(path);d=ExitDelivery(s)
            try:
                self.assertIsNone(d.claim(NOW+1));self.assertEqual(d.claim(NOW+180001)['id'],item['id'])
            finally:s.close()
    def test_fcm_adapter_uses_private_device_not_topic_and_short_inbox_hint(self):
        from offline_daemon import daemon
        captured=[]
        fake=SimpleNamespace(Message=lambda **k:k,Notification=lambda **k:k,AndroidConfig=lambda **k:k,
            AndroidNotification=lambda **k:k,send=lambda msg:captured.append(msg))
        with patch.object(daemon,'messaging',fake,create=True),patch.object(daemon,'FCM_INITIALIZED',True):
            data={'eventType':'POSITION_EXIT_NOTICE','expiresAtMs':str(int(__import__('time').time()*1000)+300000)}
            self.assertTrue(daemon.send_position_hint('private-test-token',data))
        self.assertEqual(captured[0]['token'],'private-test-token');self.assertNotIn('topic',captured[0])
        self.assertEqual(captured[0]['android']['notification']['visibility'],'private')

if __name__=='__main__':unittest.main()
