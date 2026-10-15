"""Binance spot cache. Sequence gaps invalidate depth until a fresh REST bootstrap."""
import copy
import math
import threading
from .config import QUOTE_MAX_AGE_MS

INTERVALS = {'1m': 60000, '5m': 300000, '15m': 900000, '1h': 3600000, '4h': 14400000}

def positive(value, zero=False):
    result = float(value)
    if not math.isfinite(result) or (result < 0 if zero else result <= 0):
        raise ValueError('Invalid market number')
    return result

def rest_candle(row):
    return dict(time=int(row[0]), open=positive(row[1]), high=positive(row[2]),
                low=positive(row[3]), close=positive(row[4]), volume=positive(row[5], True),
                close_time=int(row[6]), taker_buy_base=positive(row[9], True), is_closed=False)

class MarketCache:
    def __init__(self):
        self.lock = threading.RLock()
        self.changed = threading.Event()
        self.reset()

    def reset(self):
        with self.lock:
            self.connected = False
            self.reason = 'CONNECTING'
            self.bids, self.asks, self.bars = {}, {}, {k: {} for k in INTERVALS}
            self.last_id = None
            self.depth_ready = False
            self.depth_at = self.depth_received = self.ticker_at = self.clock_at = 0
            self.offset_ms = self.clock_uncertainty_ms = 0
            self.ticker = None
            self.candle_events = {}
            self.last_trade_id = None
            self.trade_at = 0
            self.trades = []

    def sync_clock(self, server_ms, sent_ms, received_ms):
        with self.lock:
            self.offset_ms = server_ms - (sent_ms + received_ms) / 2
            self.clock_uncertainty_ms = (received_ms - sent_ms) / 2
            self.clock_at = received_ms

    def seed(self, series, depth, received_ms):
        with self.lock:
            for interval, rows in series.items():
                self.bars[interval] = {int(r[0]): rest_candle(r) for r in rows}
                for candle in self.bars[interval].values():
                    candle['is_closed'] = candle['close_time'] < received_ms + self.offset_ms
            self.bids = {positive(p): positive(q) for p,q in depth['bids'] if float(q) > 0}
            self.asks = {positive(p): positive(q) for p,q in depth['asks'] if float(q) > 0}
            self.last_id = int(depth['lastUpdateId'])
            self.depth_ready = False  # A websocket bridging event is mandatory.
            self.connected = True
            self.reason = 'WAITING_FOR_STREAM'

    def disconnect(self, reason):
        with self.lock:
            self.connected = False
            self.depth_ready = False
            self.reason = reason
            self.changed.set()

    def ingest(self, payload, received_ms):
        d = payload.get('data', payload)
        with self.lock:
            if d.get('e') == 'serverShutdown':
                raise ValueError('SERVER_SHUTDOWN')
            if d.get('s') != 'BTCUSDT':
                raise ValueError('Unexpected symbol')
            event = int(d.get('E', received_ms + self.offset_ms))
            if event > received_ms + self.offset_ms + 1000:
                raise ValueError('Future exchange event')
            kind = d.get('e')
            if kind == 'depthUpdate':
                if self.last_id is None:
                    raise ValueError('Depth snapshot missing')
                first, last = int(d['U']), int(d['u'])
                if last <= self.last_id:
                    return False
                if first > self.last_id + 1 or last < first:
                    self.depth_ready = False
                    raise ValueError('DEPTH_SEQUENCE_GAP')
                for key, levels in (('b',self.bids), ('a',self.asks)):
                    for p,q in d[key]:
                        price, quantity = positive(p), positive(q, True)
                        if quantity == 0: levels.pop(price, None)
                        else: levels[price] = quantity
                if not self.bids or not self.asks or max(self.bids) >= min(self.asks):
                    self.depth_ready = False
                    raise ValueError('Crossed/empty book')
                self.last_id = last
                self.depth_at, self.depth_received, self.depth_ready = event, received_ms, True
            elif kind == '24hrTicker':
                if event <= self.ticker_at: return False
                self.ticker = dict(symbol='BTCUSDT', price=positive(d['c']),
                                   change24h=float(d['P']), high24h=positive(d['h']), low24h=positive(d['l']))
                if not math.isfinite(self.ticker['change24h']): raise ValueError('Invalid change')
                self.ticker_at = event
            elif kind == 'kline':
                k = d['k']; interval = k['i']; start = int(k['t'])
                if interval not in INTERVALS: raise ValueError('Unexpected interval')
                if event <= self.candle_events.get((interval,start), 0): return False
                previous = self.bars[interval].get(start)
                if previous and previous.get('is_closed'): return False
                # REST may already contain a later cumulative snapshot for this bar.
                if previous and positive(k['v'], True) < previous['volume']: return False
                c = dict(time=start, close_time=int(k['T']), open=positive(k['o']), high=positive(k['h']),
                         low=positive(k['l']), close=positive(k['c']), volume=positive(k['v'], True),
                         taker_buy_base=positive(k['V'], True), is_closed=bool(k['x']))
                if c['is_closed'] and c['close_time'] > event: raise ValueError('Premature closed candle')
                self.bars[interval][start] = c
                self.candle_events[(interval,start)] = event
                for old in sorted(self.bars[interval])[:-256]:
                    del self.bars[interval][old]
                    self.candle_events.pop((interval,old), None)
            elif kind == 'aggTrade':
                trade_id = int(d['a'])
                if self.last_trade_id is not None:
                    if trade_id <= self.last_trade_id: return False
                    if trade_id != self.last_trade_id + 1: raise ValueError('TRADE_SEQUENCE_GAP')
                self.last_trade_id, self.trade_at = trade_id, event
                self.trades.append({'id':trade_id, 'atMs':int(d['T']), 'price':positive(d['p']),
                                    'quantity':positive(d['q']), 'buyerMaker':bool(d['m'])})
                self.trades = self.trades[-2000:]
            else:
                return False
            self.changed.set()
            return True

    def snapshot(self, local_ms):
        with self.lock:
            now = int(local_ms + self.offset_ms)
            issues = []
            if not self.connected: issues.append(self.reason)
            if local_ms - self.clock_at > 300000 or self.clock_uncertainty_ms > 1000 or abs(self.offset_ms) > 5000:
                issues.append('CLOCK_UNCERTAIN')
            if not self.depth_ready or not 0 <= now-self.depth_at <= QUOTE_MAX_AGE_MS:
                issues.append('DEPTH_UNAVAILABLE')
            if not self.ticker or not 0 <= now-self.ticker_at <= QUOTE_MAX_AGE_MS:
                issues.append('TICKER_UNAVAILABLE')
            if not 0 <= now-self.trade_at <= QUOTE_MAX_AGE_MS: issues.append('TRADE_STREAM_UNAVAILABLE')
            series = {}
            for interval, step in INTERVALS.items():
                bars = [copy.deepcopy(v) for _,v in sorted(self.bars[interval].items()) if v.get('is_closed') and v['close_time'] < now]
                required = 64 if interval == '15m' else 32
                if len(bars) < required or not bars or not 0 <= now-bars[-1]['close_time'] <= step+10000:
                    issues.append('BARS_MISSING_OR_STALE:'+interval)
                elif any(b['time']-a['time'] != step for a,b in zip(bars,bars[1:])):
                    issues.append('BAR_GAP:'+interval)
                series[interval] = bars
            bid = max(self.bids, default=0); ask = min(self.asks, default=0)
            bv = sum(q for _,q in sorted(self.bids.items(),reverse=True)[:20])
            av = sum(q for _,q in sorted(self.asks.items())[:20])
            ticker = dict(self.ticker or {}, bid_price=bid, ask_price=ask, timestamp=self.depth_at)
            book = {'is_valid':self.depth_ready, 'spread':(ask-bid)/((ask+bid)/2)*100 if bid and ask else 999,
                    'imbalance':(bv-av)/(bv+av) if bv+av else 0, 'bid_vol':bv, 'ask_vol':av}
            return {'schema':1, 'atMs':now, 'receivedAtMs':local_ms, 'clockOffsetMs':self.offset_ms,
                    'clockUncertaintyMs':self.clock_uncertainty_ms,
                    'source':'BINANCE_SPOT_WS', 'healthy':not issues, 'issues':issues,
                    'ticker':ticker, 'book':book, 'series':series,
                    'depthUpdateId':self.last_id, 'depthReceivedAtMs':self.depth_received,
                    'lastTradeId':self.last_trade_id}
