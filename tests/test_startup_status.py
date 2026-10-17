import unittest
import threading
import time
from types import SimpleNamespace
from cryptog.runtime import Runtime

class StartupStatusTests(unittest.TestCase):
    def test_radar_response_avoids_database_and_keeps_health_and_snapshot(self):
        runtime = object.__new__(Runtime)
        runtime.lock = threading.Lock()
        runtime.latest = {'atMs': 123, 'macro': {'rsi': 50}, 'signal': None}
        runtime.positions = []
        runtime.live = True
        runtime.heartbeat_ms = int(time.time()*1000)
        runtime.feed = SimpleNamespace(is_alive=lambda: True, heartbeat_ms=runtime.heartbeat_ms)
        # No database, AI or notification worker exists: the light response must not access them.
        result = runtime.status(radar_only=True)
        self.assertTrue(result['runtimeHealthy'])
        self.assertTrue(result['feedHealthy'])
        self.assertEqual(result['snapshot'], runtime.latest)
        self.assertNotIn('aiState', result)
        result['snapshot']['macro']['rsi'] = 99
        self.assertEqual(runtime.latest['macro']['rsi'], 50)
        runtime.heartbeat_ms = 1
        runtime.feed.heartbeat_ms = 1
        result = runtime.status(radar_only=True)
        self.assertFalse(result['runtimeHealthy'])
        self.assertFalse(result['feedHealthy'])
        self.assertNotIn('evolution', result)

    def test_radar_response_includes_guard_fields_when_the_runtime_has_them(self):
        runtime = object.__new__(Runtime)
        runtime.lock = threading.Lock()
        runtime.latest = {'atMs': 123}
        runtime.positions = []
        runtime.live = False
        runtime.heartbeat_ms = int(time.time()*1000)
        runtime.feed = SimpleNamespace(is_alive=lambda: True, heartbeat_ms=runtime.heartbeat_ms)
        runtime.tracker = SimpleNamespace(status=lambda now: {'breaker': {'pausedUntil': 0, 'consecutiveStops': 0, 'dayR': 0}})
        runtime.context_feed = SimpleNamespace(health=lambda now: {'healthy': True})
        runtime.derivatives = SimpleNamespace(health=lambda now: {'healthy': False})
        runtime.evolution = SimpleNamespace(status=lambda now: {'modules': [{'module': 'S1'}], 'promotions': 0})
        runtime.continuity = SimpleNamespace(status=lambda now: {'cost': None})
        result = runtime.status(radar_only=True)
        self.assertEqual(result['shortHorizonV2']['breaker']['pausedUntil'], 0)
        self.assertTrue(result['context']['healthy'])
        self.assertFalse(result['derivatives']['healthy'])
        self.assertEqual(result['evolution']['modules'][0]['module'], 'S1')
        self.assertIsNone(result['continuity']['cost'])
        self.assertNotIn('aiState', result)

if __name__ == '__main__':
    unittest.main()
