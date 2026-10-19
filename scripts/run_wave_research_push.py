"""Samsung-only observation transport reading frozen shadow evidence, never writing it."""
import argparse
import datetime
import hashlib
import json
from pathlib import Path
import signal
import sqlite3
import sys
import threading
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scratch'))
from cryptog.wave_push import ResearchOutbox,payload_from_event,transport_fields
from cryptog.wave_holding import HoldingMonitor,owned_actions,position_snapshot


def readonly(path):
    db=sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True,timeout=5)
    db.execute('PRAGMA query_only=ON')
    return db


class Sender:
    def __init__(self,root):
        self.root=Path(root)
        self.output=self.root/'data';self.output.mkdir(exist_ok=True)
        self.config=json.loads((self.root/'config.json').read_text())
        self.source=readonly(self.config['shadowDatabase'])
        self.monitor=readonly(self.config['monitorDatabase'])
        self.outbox=ResearchOutbox(self.output/'push.sqlite3')
        self.holding=HoldingMonitor(self.outbox,self.source)
        manifest=json.loads((self.root/'manifest.json').read_text())
        for name,digest in manifest['files'].items():
            if hashlib.sha256((self.root/name).read_bytes()).hexdigest()!=digest:
                raise ValueError('SOURCE_HASH_MISMATCH')
        import firebase_admin
        from firebase_admin import credentials
        firebase_admin.initialize_app(credentials.Certificate(self.config['firebaseCertificate']))

    def target(self):
        # Reload registry and binding every send so revocation/rebinding takes effect.
        registry=json.loads(Path(self.config['deviceRegistry']).read_text())
        owner=registry.get('owner-samsung-s24plus')
        if not owner or owner.get('write') is not True:raise ValueError('OWNER_NOT_AUTHORIZED')
        row=self.monitor.execute('SELECT token FROM exit_devices WHERE device=?',(owner['sha256'],)).fetchone()
        if not row or not row[0]:raise ValueError('OWNER_NOT_BOUND')
        return row[0]

    def paper_actions(self):
        registry=json.loads(Path(self.config['deviceRegistry']).read_text())
        owner=registry.get('owner-samsung-s24plus')
        if not owner or owner.get('write') is not True:raise ValueError('OWNER_NOT_AUTHORIZED')
        return owned_actions(Path(self.config['paperJournal']),owner['sha256'],self.config.get('legacyPaperEventIds',[])),owner['sha256']

    def send(self,data,dry_run=False):
        from firebase_admin import messaging
        if data['phase']=='HOLDING_EXHAUSTION' and data['lifecycle']=='ACTIVE' and not dry_run:
            actions,owner=self.paper_actions();p=position_snapshot(actions,owner,int(time.time()*1000))
            if p['remainingQuantity']<=0 or p['revision']!=data['position']['revision']:raise ValueError('POSITION_CHANGED_BEFORE_SEND')
        title,body,fields=transport_fields(data)
        remaining=data['expiresAt']-int(time.time()*1000)
        if remaining<=0:raise ValueError('EXPIRED_BEFORE_TRANSPORT')
        message=messaging.Message(token=self.target(),
            notification=messaging.Notification(title=title,body=body),data=fields,
            android=messaging.AndroidConfig(priority='high',ttl=datetime.timedelta(milliseconds=min(remaining,120000)),
                notification=messaging.AndroidNotification(channel_id='shot_crypto_signals_v2',
                    sound='default',default_vibrate_timings=True,tag=data['eventId'])))
        return messaging.send(message,dry_run=dry_run)

    def dry_check(self):
        now=int(time.time()*1000)
        data,_=payload_from_event(dict(eventId=f'B-R00:5:{now-60000}',group='B-R00',window=5,
            phase='DOWN_START',evidence={'validationOnly':True}),now,now,now)
        self.send(data,dry_run=True)
        return dict(dryRunAccepted=True,actualMessagesSent=0,target='owner-samsung-s24plus',
                    label='研究观察·未验证',phoneDeliveryVerified=False)

    def tick(self):
        now=int(time.time()*1000)
        self.config=json.loads((self.root/'config.json').read_text())
        meta={k:json.loads(v) for k,v in self.source.execute("SELECT key,value FROM meta WHERE key IN ('startMs','heartbeatMs','status')")}
        state='WAITING_UNSEEN_WINDOW'
        last_error=None
        if not self.config.get('enabled'):state='DISABLED'
        elif not 0<=now-meta.get('heartbeatMs',0)<=15000:state='SHADOW_STALE'
        elif meta.get('status') not in ['WARMUP_BEFORE_UNSEEN_WINDOW','COLLECTING_PROSPECTIVE_SHADOW']:state='SHADOW_NOT_READY'
        elif now>=meta['startMs']:
            state='OBSERVATION_PUSH_ENABLED'
            cursor=self.outbox.get('sourceRowId',0)
            rows=self.source.execute('SELECT rowid,feature_ms,decision_ms,payload FROM events WHERE rowid>? ORDER BY rowid LIMIT 500',(cursor,)).fetchall()
            for rowid,feature,decision,text in rows:
                try:
                    data,config=payload_from_event(json.loads(text),feature,decision,int(time.time()*1000))
                    self.outbox.ingest(data,config,now)
                except (ValueError,KeyError,TypeError) as error:
                    self.outbox.put('skippedCount',self.outbox.get('skippedCount',0)+1)
                    self.outbox.put('lastSkip',dict(rowid=rowid,reason=type(error).__name__+':'+str(error)[:80]))
                self.outbox.put('sourceRowId',rowid)
        q=self.source.execute('SELECT payload FROM quotes ORDER BY at_ms DESC,rowid DESC LIMIT 1').fetchone()
        quote=json.loads(q[0]) if q else None
        holding_status=dict(state='DISABLED')
        if self.config.get('enabled') and self.config.get('paperJournal'):
            try:
                actions,owner=self.paper_actions()
                holding_status=self.holding.tick(actions,owner,quote,int(time.time()*1000))
            except Exception as error:holding_status=dict(state='BLOCKED',reason=type(error).__name__+':'+str(error)[:80])
        if self.config.get('enabled') and state not in ['SHADOW_STALE','SHADOW_NOT_READY']:
            self.outbox.step(quote,int(time.time()*1000),self.send)
        try:self.target();bound=True
        except Exception as error:bound=False;last_error=type(error).__name__
        report=dict(heartbeatMs=int(time.time()*1000),state=state,enabled=self.config.get('enabled'),
            targetBound=bound,lastError=last_error,startMs=meta.get('startMs'),
            deliveryStates=dict(self.outbox.db.execute('SELECT state,count(*) FROM deliveries GROUP BY state')),
            skippedCount=self.outbox.get('skippedCount',0),lastSkip=self.outbox.get('lastSkip'),
            label='研究观察·未验证',tradeTierEnabled=False,
            supportedPhases=['DOWN_START','SELL_EXHAUSTION','REBOUND_CONFIRMED','INVALIDATED','HOLDING_EXHAUSTION'],
            actualUserPositionReminders=bool(self.config.get('paperJournal')),paperHolding=holding_status,phoneDeliveryVerified=False)
        temp=self.output/'status.tmp';temp.write_text(json.dumps(report,ensure_ascii=False,indent=2))
        temp.replace(self.output/'status.json')
        return report


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--root',required=True)
    parser.add_argument('--dry-check',action='store_true');parser.add_argument('--once',action='store_true')
    args=parser.parse_args();sender=Sender(args.root)
    if args.dry_check:print(json.dumps(sender.dry_check(),ensure_ascii=True));return
    stop=threading.Event();signal.signal(signal.SIGTERM,lambda *_:stop.set());signal.signal(signal.SIGINT,lambda *_:stop.set())
    while not stop.is_set():
        try:
            report=sender.tick()
            if args.once:print(json.dumps(report,ensure_ascii=True));break
        except Exception as error:
            print(type(error).__name__,flush=True)
            if args.once:raise
        stop.wait(2)

if __name__=='__main__':main()
