"""Continuous, bounded spot research ingestion; independent of signal generation."""
import json
import math
import threading
import time
import urllib.request
from .kline_store import ResearchStore, INTERVAL_MS, KLINE_URL, bar_from_kline


def validated(rows, interval, now):
    step = INTERVAL_MS[interval]
    result = []
    for raw in rows:
        b = bar_from_kline(raw)
        if b['close_time'] >= now:
            continue
        if b['time'] % step or b['close_time'] != b['time'] + step - 1:
            raise ValueError('KLINE_ALIGNMENT')
        if not all(math.isfinite(b[k]) and b[k] > 0 for k in ('open','high','low','close')):
            raise ValueError('KLINE_PRICE')
        if b['low'] > min(b['open'],b['close']) or b['high'] < max(b['open'],b['close']):
            raise ValueError('KLINE_OHLC')
        if not math.isfinite(b['volume']) or not 0 <= b['taker_buy_base'] <= b['volume']:
            raise ValueError('KLINE_VOLUME')
        result.append(b)
    return result


def coverage(store, now):
    report = store.coverage()
    for interval, step in INTERVAL_MS.items():
        r = report[interval]
        r['missingBars'] = 0 if not r['count'] else (r['end']-r['start'])//step+1-r['count']
        r['latestClosedOpen'] = now//step*step-step
        r['tailMissingBars'] = None if r['end'] is None else max(0,(r['latestClosedOpen']-r['end'])//step)
        r['completeWithinStoredRange'] = bool(r['count']) and r['missingBars']==0
    return report


class SpotResearchFeed(threading.Thread):
    def __init__(self, path, stop, fetch=None):
        super().__init__(name='spot-research',daemon=True)
        self.path,self.stop = path,stop
        self.fetch = fetch or self._fetch
        self.lock = threading.Lock()
        self.view = {'updatedMs':0,'healthy':False,'coverage':{},'errors':{}}

    @staticmethod
    def _fetch(interval,start,end):
        request=urllib.request.Request(KLINE_URL.format(symbol='BTCUSDT',interval=interval,start=start,end=end),headers={'User-Agent':'cryptog-research-v2'})
        with urllib.request.urlopen(request,timeout=8) as response:
            return json.loads(response.read().decode())

    def step(self, now):
        store=ResearchStore(self.path)
        errors={}
        try:
            for interval,span in INTERVAL_MS.items():
                if self.stop.is_set():break
                try:
                    latest=now//span*span-span
                    have=store.max_open_time('BTCUSDT',interval)
                    # Seed 300 bars only; long historical research is a separate explicit backfill.
                    start=latest-299*span if have is None else min(latest,have+span)
                    store.upsert_klines('BTCUSDT',interval,validated(self.fetch(interval,start,now-1),interval,now))
                    gap=store.db.execute('''SELECT next_open FROM (
                      SELECT open_time+? AS next_open, lead(open_time) OVER (ORDER BY open_time) AS following
                      FROM klines WHERE symbol='BTCUSDT' AND interval=?) WHERE following>next_open LIMIT 1''',(span,interval)).fetchone()
                    if gap:
                        store.upsert_klines('BTCUSDT',interval,validated(self.fetch(interval,gap[0],min(now-1,gap[0]+999*span+span-1)),interval,now))
                except Exception as exc:
                    errors[interval]=type(exc).__name__
            report=coverage(store,now)
            good=not errors and all(report[tf]['count'] and report[tf]['missingBars']==0 and report[tf]['tailMissingBars']==0 for tf in INTERVAL_MS)
            with self.lock:self.view={'updatedMs':now,'healthy':good,'coverage':report,'errors':errors,'bootstrapBars':300}
        finally:store.close()
        return self.view

    def status(self,now):
        with self.lock:
            return dict(self.view,healthy=self.view['healthy'] and 0<=now-self.view['updatedMs']<=120000)

    def run(self):
        while not self.stop.is_set():
            try:self.step(int(time.time()*1000))
            except Exception as exc:
                with self.lock:self.view=dict(self.view,healthy=False,errors={'worker':type(exc).__name__})
            self.stop.wait(30)
