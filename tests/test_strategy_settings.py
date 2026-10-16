import tempfile
import pathlib
import unittest
from cryptog.storage import EventStore
from cryptog.strategy_settings import StrategySettings, KEYS

class StrategySettingsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db_path = str(pathlib.Path(self.tmp) / 'events.sqlite3')
        self.store = EventStore(self.db_path)
        self.settings = StrategySettings(self.store)

    def tearDown(self):
        self.store.close()

    def test_default_settings(self):
        cfg = self.settings.get()
        self.assertEqual(cfg['revision'], 0)
        self.assertEqual(set(cfg['activeStrategies'].keys()), set(KEYS))
        self.assertTrue(all(cfg['activeStrategies'].values()))

    def test_update_revision_and_persistence(self):
        new_flags = {'BURST_BREAKOUT': False, 'FLASH_CRASH_REBOUND': True, 'RANGE_OSCILLATION': False}
        res = self.settings.put({'revision': 0, 'activeStrategies': new_flags})
        self.assertEqual(res['revision'], 1)
        self.assertEqual(res['activeStrategies'], new_flags)

        # Re-read
        read_back = self.settings.get()
        self.assertEqual(read_back['revision'], 1)
        self.assertEqual(read_back['activeStrategies'], new_flags)

        # Persistence across new instance on same store
        new_instance = StrategySettings(self.store)
        self.assertEqual(new_instance.get(), res)

    def test_revision_conflict(self):
        new_flags = {'BURST_BREAKOUT': True, 'FLASH_CRASH_REBOUND': True, 'RANGE_OSCILLATION': True}
        self.settings.put({'revision': 0, 'activeStrategies': new_flags})

        # Concurrent update with stale revision 0 must fail
        with self.assertRaises(ValueError) as ctx:
            self.settings.put({'revision': 0, 'activeStrategies': new_flags})
        self.assertIn('Configuration changed', str(ctx.exception))

    def test_invalid_keys_and_types_rejected(self):
        with self.assertRaises(ValueError):
            self.settings.put({'revision': 0, 'activeStrategies': {'UNKNOWN': True}})
        with self.assertRaises(ValueError):
            self.settings.put({'revision': 0, 'activeStrategies': {'BURST_BREAKOUT': 'yes', 'FLASH_CRASH_REBOUND': True, 'RANGE_OSCILLATION': True}})

if __name__ == '__main__':
    unittest.main()
