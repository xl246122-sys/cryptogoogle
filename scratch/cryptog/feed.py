"""Live adapter; importing this module never opens sockets."""
import json
import threading
import time
from .market import INTERVALS

STREAMS = ['btcusdt@depth@100ms', 'btcusdt@ticker', 'btcusdt@aggTrade'] + ['btcusdt@kline_'+k for k in INTERVALS]

class BinanceFeed(threading.Thread):
    def __init__(self, cache, stop):
        super().__init__(name='market-feed', daemon=True)
        self.cache, self.stop = cache, stop
        self.heartbeat_ms = 0
        self.error = None

    def run(self):
        import requests
        import websocket
        session = requests.Session()
        next_request = 0.0
        def get(path):
            nonlocal next_request
            self.stop.wait(max(0, next_request-time.monotonic()))
            if self.stop.is_set(): raise RuntimeError('STOPPED')
            response = session.get('https://data-api.binance.vision/api/v3/'+path, timeout=5)
            next_request = time.monotonic()+0.25
            if response.status_code in (418,429):
                next_request = time.monotonic()+max(60, float(response.headers.get('Retry-After',60)))
                raise RuntimeError('EXCHANGE_RATE_LIMIT')
            response.raise_for_status()
            return response.json()
        def clock():
            samples = []
            for _ in range(3):
                sent = int(time.time()*1000)
                server = get('time')['serverTime']
                received = int(time.time()*1000)
                samples.append((received-sent,server,sent,received))
            _,server,sent,received = min(samples)
            self.cache.sync_clock(server,sent,received)
        backoff = 1
        while not self.stop.is_set():
            ws = None
            try:
                self.cache.reset()
                clock()
                # Subscribe before REST snapshot; socket buffers updates needed for the bridge.
                ws = websocket.create_connection('wss://data-stream.binance.vision/stream?streams='+'/'.join(STREAMS), timeout=5)
                seed_cutoff = int(time.time()*1000)
                series = {k:get('klines?symbol=BTCUSDT&interval='+k+'&limit='+('128' if k=='15m' else '64')) for k in INTERVALS}
                depth = get('depth?symbol=BTCUSDT&limit=5000')
                self.cache.seed(series, depth, seed_cutoff)
                started = time.monotonic(); last_clock = started
                while not self.stop.is_set():
                    raw = ws.recv()
                    if not raw: raise RuntimeError('EMPTY_STREAM')
                    now = int(time.time()*1000)
                    self.cache.ingest(json.loads(raw), now)
                    self.heartbeat_ms = now
                    if self.cache.depth_ready and self.cache.ticker:
                        backoff, self.error = 1, None
                    if time.monotonic()-last_clock > 60:
                        clock(); last_clock = time.monotonic()
                    if time.monotonic()-started > 23*3600:
                        break
            except Exception as exc:
                self.error = type(exc).__name__+':'+str(exc)[:160]
            finally:
                self.cache.disconnect(self.error or 'RECONNECTING')
                if ws:
                    try: ws.close()
                    except Exception: pass
            self.stop.wait(backoff)
            backoff = min(60,backoff*2)
