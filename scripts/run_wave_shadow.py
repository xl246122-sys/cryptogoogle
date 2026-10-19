"""Sidecar: production DBs read-only; all new writes stay in --output."""
import argparse
import hashlib
import json
import signal
import sqlite3
import sys
import time
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scratch'))
from cryptog.wave_shadow import ShadowStore, encoded


def readonly(path):
    db = sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro', uri=True, timeout=5)
    db.execute('PRAGMA query_only=ON')
    return db


def detect(df, start_ms):
    """Same B features and confirmation, applied to a closed prefix only.

    Event IDs use UTC timestamps rather than rolling-array indices. No censored
    tail becomes a timeout until the 30-minute confirmation window really ends.
    """
    import numpy as np
    from research_btc_stage_b import build_features, confirmation, GROUPS
    from report_btc_wave_space import event_starts, WINDOWS
    minute, day = 60000, 1440
    boundary_ms = int(df.time.iloc[-1])//86400000*86400000-86400000
    start = int(np.searchsorted(df.time.to_numpy(), boundary_ms))
    f, _ = build_features(df, start)
    masks = dict(f['masks'])
    masks['D0'] = {}
    for w in WINDOWS:
        high = df.high.rolling(w).max()
        draw = ((high-df.close)/high*100).to_numpy()
        hit = np.zeros(len(df), dtype=bool)
        for boundary in range(start, len(df), day):
            past = draw[boundary-90*day:boundary]
            if len(past)!=90*day or not np.isfinite(past).all():
                raise ValueError('INSUFFICIENT_CALIBRATION')
            threshold = np.quantile(past, .95)
            hit[boundary:boundary+day] = draw[boundary:boundary+day]>=threshold
        masks['D0'][w] = hit
    output = []
    for group, (detector, confirm, exit_mode) in GROUPS.items():
        for window, mask in masks[detector].items():
            for i in event_starts(mask):
                i = int(i)
                if i < len(df)-32 or int(df.time.iloc[i])+minute < start_ms:
                    continue
                identity = f'{group}:{window}:{int(df.time.iloc[i])}'
                confirmed, transitions = confirmation(f, i, confirm)
                phases = [(i, 'DOWN_START', None, {})]+[(k, phase.removeprefix('OBSERVED_'), reason, evidence)
                    for k, phase, reason, evidence in transitions]
                plan = None
                if confirmed is not None:
                    j = confirmed
                    ref = float(f['bars'][j,3])
                    plan = dict(group=group, window=window, entryLow=ref*.999, entryHigh=ref*1.001,
                        stop=min(float(f['bars'][i:j+1,2].min())-.15*float(f['atr'][j]), ref*.9965),
                        target=float(f['bars'][i-max(window,60):i,1].max())*.9985,
                        holdMinutes=30 if window<=15 else 360, minNet=.8 if window<=15 else 1.,
                        exitMode=exit_mode)
                    phases.append((j,'REBOUND_CONFIRMED',None,{}))
                elif i+30 < len(df):
                    phases.append((i+30,'INVALIDATED','CONFIRM_TIMEOUT',{}))
                for k, phase, reason, evidence in phases:
                    feature_ms = int(df.time.iloc[k])+minute
                    output.append((f'{identity}:{feature_ms}:{phase}', feature_ms,
                        dict(eventId=identity, group=group, window=window, phase=phase,
                            reason=reason, evidence=evidence, plan=plan if phase=='REBOUND_CONFIRMED' else None)))
    return output, f


class Runner:
    def __init__(self, library, output, protocol, seed):
        import pandas as pd
        self.pd = pd
        self.out = Path(output)
        self.out.mkdir(parents=True, exist_ok=True)
        self.store = ShadowStore(self.out/'shadow.sqlite3')
        self.source = readonly(Path(library)/'monitor-v1.sqlite3')
        self.research = readonly(Path(library)/'research.sqlite3')
        self.protocol = json.loads(Path(protocol).read_text(encoding='utf-8'))
        manifest_path=ROOT/'deployment-manifest.json'
        if manifest_path.exists():
            manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
            for name,digest in manifest['files'].items():
                if hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=digest:
                    raise ValueError('FROZEN_SOURCE_CHANGED')
            self.store.set('deploymentManifestSha256',hashlib.sha256(manifest_path.read_bytes()).hexdigest())
        self.start = self.protocol['prospective']['startMs']
        self.end = self.protocol['prospective']['endExclusiveMs']
        self.store.set('startMs', self.start)
        self.store.db.execute('''CREATE TABLE IF NOT EXISTS bars(time INTEGER PRIMARY KEY,
            open REAL,high REAL,low REAL,close REAL,volume REAL,close_time INTEGER,taker_buy_base REAL,
            firstObservedMs INTEGER,origin TEXT)''')
        if not self.store.db.execute('SELECT 1 FROM bars LIMIT 1').fetchone():
            expected = '28720fd4d5da12836425b9c1a82021c0d3396000c22c62e43f917008e8edc465'
            if hashlib.sha256(Path(seed).read_bytes()).hexdigest()!=expected:
                raise ValueError('SEED_HASH_MISMATCH')
            frame = pd.read_csv(seed)
            cutoff = self.start-94*86400000
            frame = frame[(frame.time>=cutoff)&(frame.close_time<self.start)]
            with self.store.db:
                self.store.db.executemany('INSERT INTO bars VALUES(?,?,?,?,?,?,?,?,?,?)',
                    [tuple(r)+(int(time.time()*1000),'SEEN_TRAINING_ONLY') for r in frame.itertuples(index=False,name=None)])
        self.last_detection = None
        self.last_receipt = 0

    def sync_bars(self, now):
        from cryptog.research_feed import validated
        from cryptog.kline_store import get_json, KLINE_URL
        last = self.store.db.execute('SELECT max(time) FROM bars').fetchone()[0]
        rows = self.research.execute("SELECT open_time,open,high,low,close,volume,close_time,taker_buy_base FROM klines WHERE symbol='BTCUSDT' AND interval='1m' AND open_time>? AND close_time<? ORDER BY open_time", (last,now)).fetchall()
        with self.store.db:
            self.store.db.executemany('INSERT OR IGNORE INTO bars VALUES(?,?,?,?,?,?,?,?,?,?)',
                [tuple(row)+(now,'PRODUCTION_RESEARCH_DB') for row in rows])
        gap = self.store.db.execute('''SELECT time+60000 FROM
            (SELECT time,lead(time) OVER(ORDER BY time) AS following FROM bars)
            WHERE following>time+60000 ORDER BY time LIMIT 1''').fetchone()
        last = self.store.db.execute('SELECT max(time) FROM bars').fetchone()[0]
        begin = gap[0] if gap else last+60000
        if begin < now//60000*60000:
            end = min(now-1,begin+1000*60000-1)
            bars = validated(get_json(KLINE_URL.format(symbol='BTCUSDT',interval='1m',start=begin,end=end), attempts=1),'1m',now)
            with self.store.db:
                self.store.db.executemany('INSERT OR IGNORE INTO bars VALUES(?,?,?,?,?,?,?,?,?,?)',
                    [(b['time'],b['open'],b['high'],b['low'],b['close'],b['volume'],b['close_time'],b['taker_buy_base'],now,'REST_BACKFILL_NOT_LIVE_RECEIVE') for b in bars])

    def decisions(self, now):
        import numpy as np
        from research_btc_stage_b import exit_signal
        self.sync_bars(now)
        day = now//86400000*86400000
        rows = self.store.db.execute('SELECT time,open,high,low,close,volume,close_time,taker_buy_base FROM bars WHERE time>=? AND close_time<? ORDER BY time', (day-92*86400000,now)).fetchall()
        from report_btc_wave_space import COLS
        df = self.pd.DataFrame(rows,columns=COLS)
        if df.empty or not np.array_equal(df.time.to_numpy(),np.arange(day-92*86400000,now//60000*60000,60000)):
            raise ValueError('MINUTE_GAP_OR_WARMUP')
        if not np.isfinite(df.to_numpy(dtype=float)).all() or not ((df.low>0)&(df.low<=df[['open','close']].min(axis=1))&(df.high>=df[['open','close']].max(axis=1))&(df.volume>=df.taker_buy_base)&(df.taker_buy_base>=0)&(df.close_time==df.time+59999)).all():
            raise ValueError('INVALID_BARS')
        events, features = detect(df, self.start)
        decision = int(time.time()*1000)
        if self.start <= now < self.end:
            for identity, feature_ms, payload in events:
                if feature_ms >= self.end:
                    continue
                if self.store.event(identity,feature_ms,decision,payload,self.start) and payload['plan']:
                    self.store.register_plan(identity,payload['plan'],feature_ms,decision)
            with self.store.db:
                for account, text in self.store.db.execute('SELECT account,payload FROM positions').fetchall():
                    p = json.loads(text)
                    k = int(np.searchsorted(df.time.to_numpy(), p['openedMs']//60000*60000))
                    if p['exitMode']!='E0' and not p.get('exitDueMs') and exit_signal(features,k,len(df)-1,p['exitMode']):
                        p['exitDueMs'] = int(df.time.iloc[-1])+60000+p['delayMinutes']*60000
                        self.store.db.execute('UPDATE positions SET payload=? WHERE account=?',(encoded(p),account))
        self.store.set('latestDecisionMs', decision)
        self.store.set('status', 'WARMUP_BEFORE_UNSEEN_WINDOW' if now<self.start else
                       'INTERVAL_ENDED' if now>=self.end else 'COLLECTING_PROSPECTIVE_SHADOW')

    def tick(self):
        now = int(time.time()*1000)
        maximum = self.source.execute('SELECT max(rowid) FROM events').fetchone()[0] or 0
        cursor = self.store.get('sourceRowId',max(0,maximum-100))
        previous = self.store.get('sourceLastId')
        check = self.source.execute('SELECT id FROM events WHERE rowid=?',(cursor,)).fetchone()
        if cursor>maximum or (previous and (not check or check[0]!=previous)):
            self.store.issue(now,'SOURCE_JOURNAL_ROTATED_OR_CURSOR_REMOVED')
            cursor=max(0,maximum-100)
        rows = self.source.execute('SELECT rowid,id,at_ms,kind,payload FROM events WHERE rowid>? ORDER BY rowid LIMIT 100', (cursor,)).fetchall()
        for rowid, identity, at, kind, raw in rows:
            if kind!='EVALUATION':
                self.store.set('sourceRowId',rowid)
                self.store.set('sourceLastId',identity)
                continue
            snapshot = json.loads(zlib.decompress(raw) if isinstance(raw,bytes) else raw)['input']
            # Reception and quote exchange times originate from the live cache, not this sidecar.
            quote, added = self.store.quote(identity, snapshot, now)
            if added and self.start<=now<self.end:
                self.store.step_positions(quote)
            self.store.set('sourceRowId',rowid)
            self.store.set('sourceLastId',identity)
            self.store.set('sourceCursorMs',at)
        if now-self.store.get('sourceCursorMs',0)>15000:
            self.store.set('status','SOURCE_STALE')
        if now-self.last_receipt>=30000:
            self.store.collect_delivery(self.source,self.start)
            self.last_receipt=now
        if self.last_detection != now//60000:
            self.last_detection=now//60000
            try:
                self.decisions(now)
            except Exception as error:
                self.store.issue(now,type(error).__name__+':'+str(error)[:100])
                self.store.set('status','DETECTOR_DATA_BLOCKED')
        self.store.set('heartbeatMs',int(time.time()*1000))
        report = self.store.report()
        tmp = self.out/'status.tmp'
        tmp.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        tmp.replace(self.out/'status.json')
        return report


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--library',required=True)
    parser.add_argument('--output',required=True)
    parser.add_argument('--protocol',required=True)
    parser.add_argument('--seed',required=True)
    parser.add_argument('--once',action='store_true')
    args=parser.parse_args()
    runner=Runner(args.library,args.output,args.protocol,args.seed)
    import threading
    stop=threading.Event()
    signal.signal(signal.SIGTERM,lambda *_:stop.set())
    signal.signal(signal.SIGINT,lambda *_:stop.set())
    while not stop.is_set():
        try:
            report=runner.tick()
            if args.once:
                print(json.dumps(report));break
        except Exception as error:
            runner.store.issue(int(time.time()*1000),type(error).__name__)
            print(type(error).__name__,flush=True)
            if args.once:
                raise
        stop.wait(2)


if __name__=='__main__':
    main()
