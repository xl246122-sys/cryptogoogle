import tempfile
import unittest
import time
from offline_daemon import daemon as m

class OwnerTests(unittest.TestCase):
    def test_authenticated_owner_persisted_not_client_field(self):
        with tempfile.TemporaryDirectory() as tmp:
            m.set_library_dir(tmp)
            a=dict(eventId='owner-test',alertId='owner-test',strategy='QUICK_PAPER_V2',recordType='SIM_BUY',
                actedAtMs=int(time.time()*1000)-1000,entryPrice=100.,positionSize=500.,authenticatedOwner='spoof')
            result=m.apply_user_action(a,'a'*64);self.assertTrue(result['ok'])
            self.assertEqual(m.ACTION_EVENTS['owner-test']['authenticatedOwner'],'a'*64)
            self.assertTrue(m.apply_user_action(a,'a'*64)['duplicate'])
            self.assertFalse(m.apply_user_action(a,'b'*64)['ok'])

if __name__=='__main__':unittest.main()
