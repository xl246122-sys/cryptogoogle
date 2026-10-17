"""Independent, leased, at-least-once transport. FCM acceptance is not phone receipt."""
import logging
import threading
import time
from .cost_risk import entry_is_valid
from .config import COOLDOWN_SECONDS

logger = logging.getLogger("cryptog.notifications")


def _downgrade_to_watch(signal):
    """A trial or trade card becomes 观察级 before it is sent. Watch cards stay as they are."""
    from .config import V2_TIER_TRADE, V2_TIER_TRIAL, V2_TIER_WATCH
    tier = signal.get('tier')
    label = signal.get('tier_label') or ''
    if tier not in (V2_TIER_TRIAL, V2_TIER_TRADE) and label not in ('试运行', '交易级'):
        return signal
    name = signal.get('strategy_name_zh') or ''
    if name.startswith('【') and '】' in name:
        name = name.split('】', 1)[1]
    watch = '观察级'
    stamped = dict(signal, tier=V2_TIER_WATCH, tier_label=watch, strategy_name_zh=f'【{watch}】{name}')
    v2 = dict(stamped.get('v2') or {})
    v2.update(tier=V2_TIER_WATCH, tierLabel=watch)
    stamped['v2'] = v2
    return stamped


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
        if signal.get('rule_version') == 'short-horizon-v2':
            signal = self._review(event_id, signal, now)
            if signal is None:
                return
            if not entry_is_valid(signal, snapshot['ticker'], now):
                self.store.finish(event_id, now, 'INVALIDATED', 'ENTRY_RECHECK_FAILED')
                return
        try:
            res = self.send(event_id,signal)
            if res == 'DISABLED_BY_CONFIG':
                self.store.finish(event_id,now,'CANCELLED','DISABLED_BY_CONFIG')
                self.error = None
            elif res is True:
                self.store.finish(event_id,now,'SENT',None)
                self.error = None
            else:
                self.store.finish(event_id,now,'PENDING','FCM_FAILED')
                self.error = 'FCM_FAILED'
        except Exception as exc:
            self.error = type(exc).__name__
            self.store.finish(event_id,now,'PENDING',self.error)

    def _review(self, event_id, signal, now):
        from .ai_review import ReviewLog, attach_commentary, review_signal, veto_blocks
        from .config import V2_AI_TIMEOUT_S
        try:
            veto_enabled = self.tracker.audit()['vetoEnabled'] if getattr(self, 'tracker', None) else True
            review = review_signal(signal, post=getattr(self, 'review_post', None),
                                   enabled=getattr(self, 'review_enabled', True),
                                   api_key=getattr(self, 'review_key', '') or '',
                                   timeout=getattr(self, 'review_timeout', V2_AI_TIMEOUT_S),
                                   veto_enabled=veto_enabled)
            review = attach_commentary(signal, review)
            if not self._p2_review(event_id, now, review):
                logger.error('research ai_reviews write failed; verdict not applied: %s', event_id)
                review = dict(review, verdict='PASS', fallback='RESEARCH_UNAVAILABLE', note='')
            elif review.get('verdict') == 'DOWNGRADE':
                signal = _downgrade_to_watch(signal)
            self._mirror_review(event_id, now, review)
            if veto_blocks(review):
                self.store.finish(event_id, now, 'CANCELLED', 'AI_VETO')
                return None
            return dict(signal, ai_verdict=review['verdict'], ai_note=review.get('note') or '',
                        ai_explain=review.get('explain') or '',
                        ai_anomalies=(review.get('anomalies') or {}).get('flags') or [],
                        ai_tags=review.get('tags') or [])
        except Exception:
            return dict(signal, ai_verdict='PASS', ai_note='', ai_explain='', ai_anomalies=[], ai_tags=[])

    def _mirror_review(self, event_id, now, review):
        from .ai_review import ReviewLog
        try:
            ReviewLog(self.store).save(event_id, now, review)
        except Exception as exc:
            logger.error('event ai_reviews mirror failed; research verdict stands: %s', type(exc).__name__)
        if getattr(self, 'tracker', None):
            try:
                self.tracker.set_verdict(event_id, review['verdict'])
            except Exception as exc:
                logger.error('tracker verdict mirror failed; research verdict stands: %s', type(exc).__name__)

    def _p2_review(self, event_id, now, review):
        """Research ai_reviews is the verdict authority. Retry a failed write before any push decision."""
        ledger = getattr(self, 'ledger', None)
        if ledger is None:
            return True
        last = None
        for _attempt in range(3):
            try:
                ledger.save_review(event_id, now, review)
                ledger.set_verdict(event_id, review['verdict'])
                return True
            except Exception as exc:
                last = exc
                logger.error('research ai_reviews write attempt failed: %s', type(exc).__name__)
        logger.error('research ai_reviews write failed after retries: %s', type(last).__name__ if last else 'Error')
        return False

    def run(self):
        while not self.stop.is_set():
            try: self.step(int(time.time()*1000))
            except Exception as exc: self.error = type(exc).__name__
            self.stop.wait(.5)
