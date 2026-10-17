"""Read-only, fixed-contract quote-path study; never a fill or profitability claim.

Run against a captured monitor database. No model calls or notifications.
"""
import argparse
import json
import math
import sqlite3
import zlib


def validate(path, immutable=False):
    db = sqlite3.connect('file:'+path+'?mode=ro'+('&immutable=1' if immutable else ''), uri=True)
    db.execute('BEGIN')  # One consistent WAL snapshot for counts and paths.
    counts = dict(db.execute('SELECT kind,count(*) FROM events GROUP BY kind'))
    bounds = db.execute("SELECT min(at_ms),max(at_ms) FROM events WHERE kind='EVALUATION'").fetchone()
    ai = db.execute('SELECT count(*),COALESCE(sum(is_buy),0) FROM ai_evaluations').fetchone()
    signals=[]
    for (raw,) in db.execute("SELECT payload FROM events WHERE kind='BUY_CANDIDATE' ORDER BY at_ms,id"):
        item=json.loads(raw);sig=item['signal'];sig['_candidateId']=item['alertId'];signals.append(sig)
    terminal={json.loads(raw)['alertId']:at for at,raw in db.execute("SELECT at_ms,payload FROM events WHERE kind IN ('INVALIDATED','EXPIRED') ORDER BY at_ms")}
    trials = []
    for sig in signals:
        for delay in (0,5000,15000):
            trials.append(dict(signal=sig,delay=delay,state='WAITING',entry=None,remaining=1.,gross=0.,last=None))
    lower = min((s['timestamp'] for s in signals),default=0)
    upper = max((s['timestamp']+s['max_hold_minutes']*60000 for s in signals),default=0)
    healthy=0
    for at,raw in db.execute("SELECT at_ms,payload FROM events WHERE kind='EVALUATION' AND at_ms BETWEEN ? AND ? ORDER BY at_ms,id",(lower,upper+10000)):
        event=json.loads(zlib.decompress(raw) if isinstance(raw,bytes) else raw)
        snap=event['input']
        if not snap.get('healthy'): continue
        healthy+=1
        q=snap['ticker'];ask=q.get('ask_price',0);bid=q.get('bid_price',0)
        if not 0<bid<ask or not 0<=at-q.get('timestamp',0)<=10000: continue
        for t in trials:
            s=t['signal'];start=s['timestamp']+t['delay']
            if t['state']=='WAITING' and at>=terminal.get(s['_candidateId'],float('inf')):
                t['state']='INVALIDATED_BEFORE_ENTRY';continue
            if at<start or t['state'] not in ('WAITING','OPEN'): continue
            if t['state']=='WAITING':
                if at>=s['expires_at']:
                    t['state']='NO_EXECUTABLE_ENTRY';continue
                net=(s['target_tp1']/ask-1)*100-.11
                risk=(1-s['stop_loss']/ask)*100+.11
                if not (s['entry_min']<=ask<=s['entry_max'] and ask>s.get('invalidation_price',s['stop_loss']) and net>=s.get('min_net_tp1',.4) and risk>0 and net/risk>=1.1): continue
                t.update(entry=ask,entryAt=at,state='OPEN',last=at)
            if at-t['last']>10000:
                t['state']='CENSORED_DATA_GAP';continue
            t['last']=at
            reason=None
            if bid<=max(s['stop_loss'],s.get('invalidation_price',0)): reason='STRUCTURE_EXIT'
            elif bid>=s['target_tp2']: reason='TP2'
            elif at>=s['timestamp']+s['max_hold_minutes']*60000: reason='HORIZON'
            elif bid>=s['target_tp1'] and t['remaining']==1.:
                fraction=s.get('tp1_fraction',1.)
                t['gross']+=fraction*(s['target_tp1']/t['entry']-1)*100
                t['remaining']-=fraction
                if t['remaining']==0: reason='TP1'
            if reason:
                exit_price=s['target_tp2'] if reason=='TP2' else bid
                t['gross']+=t['remaining']*(exit_price/t['entry']-1)*100
                t.update(state='CLOSED',exitAt=at,exitReason=reason)
    results=[]
    for t in trials:
        if t['state'] in ('WAITING','OPEN'): t['state']='CENSORED_END'
        s=t.pop('signal')
        t.update(signalAt=s['timestamp'],ruleVersion=s.get('rule_version'),strategy=s['strategy'])
        if t['state']=='CLOSED':t['netPctByCost']={str(cost):round(t['gross']-cost,6) for cost in (.11,.20,.30)}
        results.append(t)
    groups=[]
    for version in sorted(set(r['ruleVersion'] for r in results)):
        for delay in (0,5000,15000):
            rows=[r for r in results if r['ruleVersion']==version and r['delay']==delay]
            closed=[r for r in rows if r['state']=='CLOSED'];n=len(closed)
            wins=sum(r['netPctByCost']['0.11']>0 for r in closed)
            interval=None
            if n:
                z=1.95996398454;p=wins/n;den=1+z*z/n
                mid=(p+z*z/(2*n))/den;half=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/den
                interval=[mid-half,mid+half]
            groups.append(dict(ruleVersion=version,delayMs=delay,candidates=len(rows),closed=n,wins=wins,winRateWilson95=interval,
                               meanNetPctByCost={str(c):sum(r['netPctByCost'][str(c)] for r in closed)/n if n else None for c in (.11,.20,.30)}))
    db.close()
    return dict(method='Frozen observed candidates; next eligible recorded ask; bid exits; no parameter fitting',
                limitations=['Not actual fills','Only captured quotes; intragap execution unknown','Latency scenarios reuse the same candidates and are not independent samples','No walk-forward or out-of-sample profitability claim','AI has no historical frozen-input replay in this dataset'],
                evidenceVerdict='INSUFFICIENT_FOR_STRATEGY_VALIDATION',evaluationBoundsMs=bounds,eventCounts=counts,
                aiEvaluations=ai[0],aiAcceptedBuys=ai[1],healthyPathSamples=healthy,groups=groups,trials=results)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('database');parser.add_argument('--immutable',action='store_true',help='Only for a frozen SQLite backup, never a live database');args=parser.parse_args()
    print(json.dumps(validate(args.database,args.immutable),ensure_ascii=False,indent=2))
