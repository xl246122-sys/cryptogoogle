"""Stage-one runtime. Default shadow mode: no new alerts until promotion is authorized."""
import copy
import os
import threading
import time
from pathlib import Path
from .evaluation import evaluate
from .market import MarketCache
from .feed import BinanceFeed
from .storage import EventStore
from .notifications import NotificationWorker
from .config import COOLDOWN_SECONDS
from .migration import backup_legacy
from .positions import monitor_positions
from .exit_delivery import ExitDelivery, ExitWorker
from .security import DeviceAuth

class Runtime:
    def __init__(self, library):
        self.library = library
        self.stop = threading.Event()
        self.cache = MarketCache()
        self.lock = threading.Lock()
        self.latest = None
        self.positions = []
        Path(library.LIBRARY_DIR).mkdir(parents=True,exist_ok=True)
        backup_legacy(library.LIBRARY_DIR)
        self.store = EventStore(str(Path(library.LIBRARY_DIR)/'monitor-v1.sqlite3'))
        from .strategy_settings import StrategySettings
        self.settings=StrategySettings(self.store)
        self.feed = BinanceFeed(self.cache,self.stop)
        self.live = os.environ.get('CRYPTOG_ENABLE_BASELINE_ALERTS') == '1'
        self.worker = NotificationWorker(self.store,self.cache,self.stop,self.send,self.live)
        self.heartbeat_ms = 0
        from .observations import ObservationWorker
        self.observer=ObservationWorker(self.store,self.stop,self.library.send_fcm_alert)
        self.exit_delivery = ExitDelivery(self.store)
        self.exit_enabled = os.environ.get('CRYPTOG_ENABLE_EXIT_ALERTS') == '1'
        self.exit_worker = ExitWorker(self.exit_delivery,self.stop,self.library.send_position_hint,
            self.exit_authorized,lambda:bool(self.heartbeat_ms and 0<=int(time.time()*1000)-self.heartbeat_ms<=10000),self.exit_enabled)
        from .ai_engine import AIEngine, AIAnalystWorker
        self.ai = AIEngine(self.store, self.cache, self.library.send_fcm_alert, self.stop)
        self.ai_worker = AIAnalystWorker(self.ai, self.stop)

    def exit_authorized(self, fingerprint):
        try:
            devices=DeviceAuth(os.environ['CRYPTOG_DEVICE_AUTH_FILE']).load()
            return any(d['sha256']==fingerprint and d.get('write',False) for d in devices.values())
        except (KeyError,ValueError,OSError):return False

    def send(self, event_id, signal):
        if not self.heartbeat_ms or int(time.time()*1000)-self.heartbeat_ms>10000:
            return False
        if not self.settings.get()['activeStrategies'].get(signal['strategy'],False):
            return 'DISABLED_BY_CONFIG'
        if not self.library.FCM_INITIALIZED: return False
        self.library.record_delivery(event_id,'ATTEMPT')
        result = self.library.send_fcm_alert(('Crypto-G 实验买入候选（未验证）' if signal.get('rule_version')=='experimental-v1' else 'Crypto-G 买入候选（打开复核）'),
            f"{signal['strategy_name_zh']}；入场 {signal['entry_min']:.2f}–{signal['entry_max']:.2f}；请打开核对有效期及最新报价。",
            self.library.fcm_payload(signal))
        self.library.record_delivery(event_id,'FCM_ACCEPTED' if result else 'FAILED')
        return result

    def status(self):
        with self.lock:
            result = copy.deepcopy(self.latest)
            positions = copy.deepcopy(self.positions)
        now = int(time.time()*1000)
        with self.store.lock:
            observation_messages=[__import__('json').loads(r[0]) for r in self.store.db.execute('SELECT payload FROM observation_queue ORDER BY expires DESC LIMIT 200').fetchall()]
        obs_health = self.observer.health(now) if hasattr(self.observer, 'health') else {
            'healthy': self.observer.is_alive() and bool(getattr(self.observer, 'heartbeat', 0) and now - self.observer.heartbeat <= 10000),
            'error': getattr(self.observer, 'error', None),
        }
        return {'observationMessages':observation_messages,'ok':True,'schema':1,'mode':'BASELINE' if self.live else 'SHADOW',
                'snapshot':result,'runtimeHealthy':bool(self.heartbeat_ms and now-self.heartbeat_ms<=10000),
                'feedHealthy':self.feed.is_alive() and bool(self.feed.heartbeat_ms and now-self.feed.heartbeat_ms<=10000),
                'notificationHealthy':self.worker.is_alive() and bool(self.worker.heartbeat_ms and now-self.worker.heartbeat_ms<=10000),
                'observerHealthy': obs_health['healthy'],
                'observerError': obs_health.get('error'),
                'observationQueue': {k: obs_health[k] for k in ('pending', 'expired', 'sent') if k in obs_health},
                'aiState': self.ai.status() if hasattr(self, 'ai') else None,
                'feedError':self.feed.error,'notificationError':self.worker.error,'outbox':self.store.health(),
                'positions':positions,'positionNotifications':'DEVICE_PUSH_UNVERIFIED' if self.exit_enabled else 'SHADOW_EVENTS_ONLY',
                'exitDelivery':self.exit_delivery.health(),'exitNotificationError':self.exit_worker.error,
                'exitNotificationHealthy':self.exit_worker.is_alive() and bool(self.exit_worker.heartbeat_ms and now-self.exit_worker.heartbeat_ms<=10000)}

    def run(self):
        self.library.load_alerted_setups()
        self.api = self.library.start_model_library_server()
        self.feed.start(); self.worker.start(); self.exit_worker.start(); self.observer.start()
        if hasattr(self, 'ai_worker'): self.ai_worker.start()
        try:
            while not self.stop.is_set():
                self.cache.changed.wait(1)
                self.cache.changed.clear()
                local_ms = int(time.time()*1000)
                snapshot = self.cache.snapshot(local_ms)
                decision = evaluate(snapshot)
                flags=self.settings.get()['activeStrategies']
                if decision['signal'] and not flags.get(decision['signal']['strategy'],False):
                    decision.update(signal=None,status='WAIT_CONFIRMATION',reasons=['策略族已由云端配置关闭'])
                if os.environ.get('CRYPTOG_ENABLE_EXPERIMENTAL_ALERTS') == '1' and not decision['signal']:
                    from .experimental import experimental_signal
                    eligible=copy.deepcopy(decision)
                    eligible['research']=[r for r in decision['research'] if flags.get('RANGE_OSCILLATION' if 'RANGE' in r.get('variant','') else 'FLASH_CRASH_REBOUND',False)]
                    candidate = experimental_signal(eligible,snapshot['ticker'])
                    if candidate:
                        decision.update(signal=candidate,status='BUY_CANDIDATE')
                # Durable replay input and decision before publication/notification.
                self.store.record_evaluation(snapshot,decision)
                try:
                    self.observer.update(snapshot,decision)
                except Exception as exc:
                    self.library.logger.error('Observation update failed: %s',type(exc).__name__)
                self.store.advance_opportunities(snapshot['atMs'],snapshot['ticker'] if snapshot['healthy'] else None)
                self.library.observe_model_price(snapshot['ticker'].get('bid_price',0) if snapshot['healthy'] else 0, snapshot['atMs'])
                positions = monitor_positions(self.library,self.store,snapshot['atMs'],
                    snapshot['ticker'].get('bid_price') if snapshot['healthy'] else None,
                    snapshot['ticker'].get('timestamp') if snapshot['healthy'] else None)
                with self.lock:
                    self.latest = decision
                    self.positions = positions
                self.heartbeat_ms = local_ms
                signal = decision['signal']
                if signal:
                    event_id = f"{signal['symbol']}_{signal['strategy']}_{signal['confirmation_time']}"
                    state = self.store.opportunity(event_id,signal)
                    if self.live:
                        self.library.record_model_alert(signal)
                        if state == 'BUY_CANDIDATE' and event_id not in self.library.ALERTED_SETUPS:
                            original = self.library.OPEN_TRACKS[event_id].get('signalSnapshot',signal)
                            self.store.enqueue(event_id,original)
                # Bound snapshot/storage volume to at most one evaluation per second.
                self.stop.wait(max(0,1-(time.time()*1000-local_ms)/1000))
        finally:
            self.stop.set()
            self.api.shutdown()
            self.api.server_close()
            self.observer.join(10); self.feed.join(10); self.worker.join(10); self.exit_worker.join(10)
            if hasattr(self, 'ai_worker'): self.ai_worker.join(10)
            if not self.observer.is_alive() and not self.worker.is_alive() and not self.exit_worker.is_alive(): self.store.close()
