"""Stage-one runtime. Default shadow mode: no new alerts until promotion is authorized."""
import copy
import math
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

HOUSEKEEPING_MS = 30_000


def _json_safe(value):
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value

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
        from .v2_tracker import V2Tracker
        self.tracker = V2Tracker(self.store)
        self.worker = NotificationWorker(self.store,self.cache,self.stop,self.send,self.live)
        self.worker.tracker = self.tracker
        self.heartbeat_ms = 0
        from .observations import ObservationWorker
        self.observer=ObservationWorker(self.store,self.stop,self.library.send_fcm_alert)
        self.observer.cache=self.cache
        self.observer.prepare_enabled = False
        from .context_feed import ContextFeed
        self.context_feed = ContextFeed(self.stop)
        from .derivatives import DerivativesFeed
        self.derivatives = DerivativesFeed(self.stop, str(Path(library.LIBRARY_DIR) / 'research.sqlite3'))
        self.exit_delivery = ExitDelivery(self.store)
        self.exit_enabled = os.environ.get('CRYPTOG_ENABLE_EXIT_ALERTS') == '1'
        self.exit_worker = ExitWorker(self.exit_delivery,self.stop,self.library.send_position_hint,
            self.exit_authorized,lambda:bool(self.heartbeat_ms and 0<=int(time.time()*1000)-self.heartbeat_ms<=10000),self.exit_enabled)
        from .ai_engine import AIEngine, AIAnalystWorker, AIDeliveryWorker
        self.ai = AIEngine(self.store, self.cache, self.library.send_fcm_alert, self.stop)
        self.ai.originate_buys = False
        self.ai_worker = AIAnalystWorker(self.ai, self.stop)
        self.ai_delivery_worker = AIDeliveryWorker(self.ai, self.stop)
        from .ai_fast import AIFastWorker
        self.ai_fast_worker = AIFastWorker(self.ai,self.stop)
        self.ledger = None
        self.evolution = None
        self.continuity = None
        try:
            from .ledger import Ledger
            self.ledger = Ledger(str(Path(library.LIBRARY_DIR) / 'research.sqlite3'))
            from .evolution import Pipeline
            self.evolution = Pipeline(self.ledger)
            from .continuity import Continuity
            self.continuity = Continuity(self.ledger)
        except Exception as exc:
            library.logger.error('P2 ledger unavailable: %s', type(exc).__name__)
        self.worker.ledger = self.ledger
        self.engine_b = {}
        self._housekeeping_ms = 0

    def exit_authorized(self, fingerprint):
        try:
            devices=DeviceAuth(os.environ['CRYPTOG_DEVICE_AUTH_FILE']).load()
            return any(d['sha256']==fingerprint and d.get('write',False) for d in devices.values())
        except (KeyError,ValueError,OSError):return False

    def send(self, event_id, signal):
        if not self.heartbeat_ms or int(time.time()*1000)-self.heartbeat_ms>10000:
            return False
        if not self.settings.get()['activeStrategies'].get({'TREND_PULLBACK_BUY':'BURST_BREAKOUT'}.get(signal['strategy'], signal['strategy']), False):
            return 'DISABLED_BY_CONFIG'
        if not self.library.FCM_INITIALIZED: return False
        self.library.record_delivery(event_id,'ATTEMPT')
        if signal.get('rule_version') == 'short-horizon-v2':
            title = f"Crypto-G {signal.get('tier_label') or '观察级·未验证'} · BTC"
        elif signal.get('rule_version') in ('experimental-v1','experimental-v2'):
            title = 'Crypto-G 实验买入候选（未验证）'
        else:
            title = 'Crypto-G 买入候选（打开复核）'
        result = self.library.send_fcm_alert(title,
            f"{signal['strategy_name_zh']}；入场 {signal['entry_min']:.2f}–{signal['entry_max']:.2f}；请打开核对有效期及最新报价。",
            self.library.fcm_payload(signal))
        self.library.record_delivery(event_id,'FCM_ACCEPTED' if result else 'FAILED')
        return result

    def _guard_fields(self, now):
        fields = {}
        for key, obj, method in (
            ('shortHorizonV2', getattr(self, 'tracker', None), 'status'),
            ('context', getattr(self, 'context_feed', None), 'health'),
            ('derivatives', getattr(self, 'derivatives', None), 'health'),
            ('evolution', getattr(self, 'evolution', None), 'status'),
            ('continuity', getattr(self, 'continuity', None), 'status'),
        ):
            if obj is None:
                continue
            try:
                fields[key] = getattr(obj, method)(now)
            except Exception as exc:
                logger = getattr(getattr(self, 'library', None), 'logger', None)
                if logger is not None:
                    logger.error('Guard field %s: %s', key, type(exc).__name__)
        return fields

    def status(self, radar_only=False):
        from .market_state import present_market
        with self.lock:
            result = present_market(copy.deepcopy(self.latest))
            positions = copy.deepcopy(self.positions)
        now = int(time.time()*1000)
        if radar_only:
            # Startup radar skips message and AI scans, but the guard page still needs breaker, freshness and the lab.
            body = {'ok':True,'schema':1,'mode':'BASELINE' if self.live else 'SHADOW',
                    'snapshot':result,
                    'runtimeHealthy':bool(self.heartbeat_ms and now-self.heartbeat_ms<=10000),
                    'feedHealthy':self.feed.is_alive() and bool(self.feed.heartbeat_ms and now-self.feed.heartbeat_ms<=10000)}
            body.update(self._guard_fields(now))
            return body
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
                'aiDeliveryHealthy':self.ai_delivery_worker.is_alive() and 0 < now-self.ai_delivery_worker.heartbeat_ms <= 30000,
                'aiDeliveryError':self.ai_delivery_worker.error,
                'aiFastHealthy':self.ai_fast_worker.is_alive() and 0 <= now-self.ai_fast_worker.heartbeat_ms <= 10000,
                'aiFastError':self.ai_fast_worker.error,
                'feedError':self.feed.error,'notificationError':self.worker.error,'outbox':self.store.health(),
                'positions':positions,'positionNotifications':'DEVICE_PUSH_UNVERIFIED' if self.exit_enabled else 'SHADOW_EVENTS_ONLY',
                'exitDelivery':self.exit_delivery.health(),'exitNotificationError':self.exit_worker.error,
                'exitNotificationHealthy':self.exit_worker.is_alive() and bool(self.exit_worker.heartbeat_ms and now-self.exit_worker.heartbeat_ms<=10000),
                'context':self.context_feed.health(now),
                'derivatives':self.derivatives.health(now),
                'shortHorizonV2':self.tracker.status(now),
                'evolution': None if self.evolution is None else self.evolution.status(now),
                'continuity': None if self.continuity is None else self.continuity.status(now)}

    def run(self):
        self.library.load_alerted_setups()
        self.api = self.library.start_model_library_server()
        self.feed.start(); self.worker.start(); self.exit_worker.start(); self.observer.start(); self.context_feed.start()
        self.derivatives.start()
        if hasattr(self, 'ai_worker'): self.ai_worker.start()
        self.ai_delivery_worker.start()
        self.ai_fast_worker.start()
        try:
            while not self.stop.is_set():
                self.cache.changed.wait(1)
                self.cache.changed.clear()
                local_ms = int(time.time()*1000)
                snapshot = self.cache.snapshot(local_ms)
                snapshot['context'] = self.context_feed.latest()
                snapshot['derivatives'] = self.derivatives.latest()
                snapshot['breaker'] = self.tracker.breaker(snapshot['atMs'])
                if snapshot.get('healthy'):
                    self.tracker.step(snapshot['series'].get('1m', []), snapshot['series'].get('15m', []))
                    self.tracker.watch(snapshot['ticker'].get('bid_price'), snapshot['atMs'], snapshot.get('series'))
                decision = evaluate(snapshot)
                flags=self.settings.get()['activeStrategies']
                signal_flag = {'TREND_PULLBACK_BUY':'BURST_BREAKOUT'}.get((decision.get('signal') or {}).get('strategy'), (decision.get('signal') or {}).get('strategy'))
                kept = decision.get('signal')
                if kept and not flags.get(signal_flag, False):
                    decision.update(signal=None,status='WAIT_CONFIRMATION',reasons=['策略族已由云端配置关闭'])
                # Release stamp is part of the durable decision, still before publication.
                record = self._release(snapshot, decision, kept)
                try:
                    self.store.record_evaluation(_json_safe(snapshot), _json_safe(decision))
                except Exception as exc:
                    self.library.logger.error('Evaluation journal: %s', type(exc).__name__)
                self._p2(snapshot, decision, record)
                self._p3(snapshot['atMs'])
                if snapshot['atMs'] - self._housekeeping_ms >= HOUSEKEEPING_MS:
                    self._housekeeping_ms = snapshot['atMs']
                    self._p4(snapshot)
                    self._p5(snapshot['atMs'])
                try:
                    self.observer.update(snapshot,decision)
                except Exception as exc:
                    self.library.logger.error('Observation update failed: %s',type(exc).__name__)
                self.store.advance_opportunities(snapshot['atMs'],snapshot['ticker'] if snapshot['healthy'] else None)
                self.library.observe_model_price(snapshot['ticker'].get('bid_price',0) if snapshot['healthy'] else 0, snapshot['atMs'])
                positions = monitor_positions(self.library,self.store,snapshot['atMs'],
                    snapshot['ticker'].get('bid_price') if snapshot['healthy'] else None,
                    snapshot['ticker'].get('timestamp') if snapshot['healthy'] else None,
                    {k: snapshot['series'].get(k) for k in ('1m','15m','1h')} if snapshot.get('healthy') else None)
                with self.lock:
                    self.latest = decision
                    self.positions = positions
                self.heartbeat_ms = local_ms
                signal = decision['signal']
                if signal:
                    event_id = signal.get('structure_key') or f"{signal['symbol']}_{signal['strategy']}_{signal['confirmation_time']}"
                    state = self.store.opportunity(event_id,signal)
                    if self.live:
                        self.library.record_model_alert(signal)
                        if state == 'BUY_CANDIDATE' and event_id not in self.library.ALERTED_SETUPS:
                            original = self.library.OPEN_TRACKS[event_id].get('signalSnapshot',signal)
                            self.store.enqueue(event_id,original)
                            if signal.get('rule_version') == 'short-horizon-v2':
                                self.tracker.open(original)
                # Bound snapshot/storage volume to at most one evaluation per second.
                self.stop.wait(max(0,1-(time.time()*1000-local_ms)/1000))
        finally:
            self.stop.set()
            self.api.shutdown()
            self.api.server_close()
            self.observer.join(10); self.feed.join(10); self.worker.join(10); self.exit_worker.join(10); self.context_feed.join(10)
            if self.derivatives.ident: self.derivatives.join(10)
            if hasattr(self, 'ai_worker'): self.ai_worker.join(10)
            self.ai_delivery_worker.join(10)
            self.ai_fast_worker.join(10)
            if not any(w.is_alive() for w in (self.observer,self.worker,self.exit_worker,self.ai_worker,self.ai_delivery_worker,self.ai_fast_worker)):
                self.store.close()
                if self.ledger is not None:
                    self.ledger.close()

    def _p2(self, snapshot, decision, signal=None):
        """Record every v2 candidate, including watch tier, and settle open shadows. S5 stays research-only."""
        if self.ledger is None:
            return
        try:
            if signal is None:
                signal = decision.get('signal')
            if signal and signal.get('rule_version') == 'short-horizon-v2':
                self.ledger.record_candidate(signal)
            for item in (decision.get('shortHorizonV2') or {}).get('research') or []:
                if item.get('module') == 'S5':
                    self.ledger.record_research(item)
            if snapshot.get('healthy'):
                series = snapshot.get('series') or {}
                self.ledger.settle(series.get('1m') or [], series.get('15m') or [])
        except Exception as exc:
            self.library.logger.error('P2 ledger: %s', type(exc).__name__)

    def _release(self, snapshot, decision, kept):
        """Stamp a released module. A suppressed push still returns the candidate for the ledger."""
        record = kept if kept and kept.get('rule_version') == 'short-horizon-v2' else None
        if self.evolution is None:
            return record
        try:
            source = decision.get('signal') if decision.get('signal') else record
            if not source:
                return record
            now = snapshot['atMs']
            module = source.get('module')
            policy = self.evolution.policy(module or '')
            if policy.get('stage') == 'SHADOW':
                self.evolution.note(module, now)
            current = decision.get('signal')
            if not current or current.get('rule_version') != 'short-horizon-v2':
                return record
            from .evolution import apply_release
            breaker = snapshot.get('breaker') or {}
            paused = now < int(breaker.get('pausedUntil') or 0)
            released, reason = apply_release(current, policy, paused)
            if reason:
                reasons = list(decision.get('reasons') or [])
                reasons.append(reason)
                decision.update(signal=None, status='WAIT_CONFIRMATION', reasons=reasons)
                return record
            decision['signal'] = released
            return released if released is not None else record
        except Exception as exc:
            self.library.logger.error('P4 release: %s', type(exc).__name__)
            return record

    def _p4(self, snapshot):
        """Advance shadow and trial clocks. L1 refresh stays inside the daily maintain."""
        if self.evolution is None or self.ledger is None:
            return
        try:
            now = snapshot['atMs']
            self.evolution.tick_all(now)
            self.evolution.maintain(self.ledger.research_samples(), now)
        except Exception as exc:
            self.library.logger.error('P4 evolution: %s', type(exc).__name__)

    def _p5(self, now_ms):
        """Monthly cost report and quarterly environment-boundary report. Neither edits a rule."""
        if self.continuity is None or self.ledger is None:
            return
        try:
            self.continuity.maintain(now_ms)
        except Exception as exc:
            self.library.logger.error('P5 continuity: %s', type(exc).__name__)

    def _p3(self, now_ms):
        """Daily review, veto audit, and at most one hypothesis batch per CST week."""
        if self.ledger is None:
            return
        try:
            from .ai_review import maintain, post_hypotheses
            post = getattr(self, 'hypothesis_post', None) or getattr(self.worker, 'hypothesis_post', None)
            key = getattr(self.worker, 'review_key', '') or ''
            if post is None and key:
                post = lambda payload: post_hypotheses(key, 'deepseek-chat', payload)
            maintain(self.ledger, self.tracker.audit(), now_ms, post=post, state=self.engine_b)
        except Exception as exc:
            self.library.logger.error('P3 engine B: %s', type(exc).__name__)
