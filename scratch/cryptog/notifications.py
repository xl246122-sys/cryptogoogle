"""Independent, leased, at-least-once transport. FCM acceptance is not phone receipt."""
import threading
import time
from .cost_risk import entry_is_valid
from .config import COOLDOWN_SECONDS

class NotificationWorker(threading.Thread):
    def __init__(self, store, cache, stop, send, enabled=False):
        super().__init__(name='notification-outbox', daemon=True)
        self.store, self.cache, self.stop, self.send, self.enabled = store,cache,stop,send,enabled
        self.heartbeat_ms = 0
        self.error = None

    def step(self, local_ms):
        self.heartbeat_ms = local_ms
        if not self.enabled: return
        snapshot = self.cache.snapshot(local_ms)
        now = snapshot['atMs']
        item = self.store.claim(now, COOLDOWN_SECONDS*1000)
        if not item: return
        event_id, signal = item
        if not snapshot['healthy']:
            self.store.finish(event_id,now,'PENDING','MARKET_UNAVAILABLE')
            return
        if not entry_is_valid(signal,snapshot['ticker'],now):
            self.store.finish(event_id,now,'INVALIDATED','ENTRY_RECHECK_FAILED')
            return
        try:
            success = self.send(event_id,signal)
            self.store.finish(event_id,now,'SENT' if success else 'PENDING',None if success else 'FCM_FAILED')
            self.error = None if success else 'FCM_FAILED'
        except Exception as exc:
            self.error = type(exc).__name__
            self.store.finish(event_id,now,'PENDING',self.error)

    def run(self):
        while not self.stop.is_set():
            try: self.step(int(time.time()*1000))
            except Exception as exc: self.error = type(exc).__name__
            self.stop.wait(.5)
