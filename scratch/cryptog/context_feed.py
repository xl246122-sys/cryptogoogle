"""1D/4H/1H/15m readings for Engine A. Refreshed after each 15m close, retried every 30s."""
import json
import math
import threading
import time
import urllib.request

from .engine_v2 import build_context, s5_baseline

M15 = 900_000
STEPS = {'1d': 86_400_000, '4h': 14_400_000, '1h': 3_600_000, '15m': M15}
URL = "https://data-api.binance.vision/api/v3/klines?symbol=BTCUSDT&interval={interval}&limit=300"
SPAN_URL = "https://data-api.binance.vision/api/v3/klines?symbol=BTCUSDT&interval={interval}&limit=1000&endTime={end}"


def bars_from_klines(raw) -> list:
    return [{
        "time": int(row[0]), "open": float(row[1]), "high": float(row[2]), "low": float(row[3]),
        "close": float(row[4]), "volume": float(row[5]), "close_time": int(row[6]),
        "taker_buy_base": float(row[9]), "is_closed": False,
    } for row in raw]


def closed_history(bars, interval, now_ms):
    """REST has no closed flag. Validate event times before marking a candle closed."""
    step = STEPS[interval]
    closed = []
    for bar in bars:
        start, end = int(bar['time']), int(bar['close_time'])
        if end >= now_ms:
            continue
        if start % step or end != start + step - 1:
            raise ValueError('CONTEXT_BAR_TIME:' + interval)
        prices = [bar[k] for k in ('open', 'high', 'low', 'close')]
        if (any(not math.isfinite(p) or p <= 0 for p in prices)
                or bar['high'] < max(bar['open'], bar['close'], bar['low'])
                or bar['low'] > min(bar['open'], bar['close'])
                or not math.isfinite(bar['volume']) or bar['volume'] < 0
                or not math.isfinite(bar['taker_buy_base'])
                or not 0 <= bar['taker_buy_base'] <= bar['volume']):
            raise ValueError('CONTEXT_BAR_INVALID:' + interval)
        if closed and start - closed[-1]['time'] != step:
            raise ValueError('CONTEXT_BAR_GAP:' + interval)
        closed.append(dict(bar, is_closed=True))
    if not closed or not 0 < now_ms - closed[-1]['close_time'] <= step + 60_000:
        raise ValueError('CONTEXT_BAR_STALE:' + interval)
    return closed


class ContextFeed(threading.Thread):
    def __init__(self, stop, fetch=None):
        super().__init__(name="v2-context", daemon=True)
        self.stop = stop
        self.fetch = fetch or self._fetch
        self.custom_fetch = fetch is not None
        self.lock = threading.Lock()
        self.context = None
        self.error = None
        self.heartbeat_ms = 0
        self.updated_ms = 0
        self.last_attempt_ms = 0

    def latest(self):
        with self.lock:
            return self.context

    def health(self, now_ms: int) -> dict:
        with self.lock:
            fresh = self.context is not None and 0 <= now_ms - self.updated_ms <= 20 * 60 * 1000
            return {"healthy": fresh, "error": self.error, "updatedMs": self.updated_ms}

    def fetch_span(self, interval: str, count: int):
        """Page backward. A replaced fetch() stays a single call so tests do not hit the network."""
        if self.custom_fetch:
            return self.fetch(interval)
        end = int(time.time() * 1000)
        collected = []
        seen = set()
        while len(collected) < count:
            request = urllib.request.Request(SPAN_URL.format(interval=interval, end=end), headers={"User-Agent": "cryptog-v2"})
            with urllib.request.urlopen(request, timeout=8) as response:
                page = bars_from_klines(json.loads(response.read().decode()))
            page = [bar for bar in page if bar["time"] not in seen]
            if not page:
                break
            for bar in page:
                seen.add(bar["time"])
            collected.extend(page)
            oldest = min(bar["time"] for bar in page)
            if oldest >= end or len(page) < 1000:
                break
            end = oldest - 1
        collected.sort(key=lambda bar: bar["time"])
        return collected[-count:]

    def refresh(self, now_ms: int):
        try:
            m15 = self.fetch_span("15m", 30 * 96)
        except Exception:
            m15 = self.fetch("15m")
        m15 = closed_history(m15, '15m', now_ms)
        higher = {tf: closed_history(self.fetch(tf), tf, now_ms) for tf in ('1d', '4h', '1h')}
        ctx = build_context(higher['1d'], higher['4h'], higher['1h'], m15[-300:], now_ms)
        if ctx is not None:
            ctx["s5VolumeBaseline"] = s5_baseline(m15)
        with self.lock:
            self.updated_ms = now_ms
            self.context = ctx
            self.error = None if ctx else "CONTEXT_INCOMPLETE"
        return ctx

    def _fetch(self, interval: str):
        request = urllib.request.Request(URL.format(interval=interval), headers={"User-Agent": "cryptog-v2"})
        with urllib.request.urlopen(request, timeout=8) as response:
            return bars_from_klines(json.loads(response.read().decode()))

    def due(self, now_ms: int) -> bool:
        boundary = now_ms - (now_ms % M15)
        first = self.last_attempt_ms == 0
        new_bar = self.updated_ms < boundary and now_ms - boundary >= 5000
        retry = self.context is None and now_ms - self.last_attempt_ms >= 30_000
        return first or ((new_bar or retry) and now_ms - self.last_attempt_ms >= 30_000)

    def run(self):
        while not self.stop.is_set():
            now_ms = int(time.time() * 1000)
            self.heartbeat_ms = now_ms
            if self.due(now_ms):
                self.last_attempt_ms = now_ms
                try:
                    self.refresh(now_ms)
                except Exception as exc:
                    with self.lock:
                        self.error = type(exc).__name__
            self.stop.wait(5)
