"""Append-only candidate stages. Counts are distinct stage entries, never trade counts."""
import hashlib
import json

SCHEMA='''CREATE TABLE IF NOT EXISTS funnel_events(
 id TEXT PRIMARY KEY,candidate_id TEXT NOT NULL,at_ms INTEGER NOT NULL,
 stage TEXT NOT NULL,reason TEXT,payload TEXT NOT NULL);
 CREATE INDEX IF NOT EXISTS funnel_by_candidate ON funnel_events(candidate_id,at_ms);'''


def reason_code(issue):
    if not issue:return 'EXECUTABLE'
    if '止损距离' in issue and '大于' in issue:return 'STOP_TOO_WIDE'
    for word,code in [('止损距离','STOP_DISTANCE'),('净盈亏比','NET_RR'),('TP1 净','NET_TARGET'),('上冲','ESCAPED'),('触及止损','INVALIDATED'),('挂单区间','WAIT_RETEST'),('过期','EXPIRED'),('未收盘','DATA_UNAVAILABLE')]:
        if word in issue:return code
    return 'STRUCTURE_REJECTED'


def stage(ledger,candidate,at,kind,reason=None,payload=None,event_id=None):
    identity=event_id or hashlib.sha256(json.dumps([candidate,kind,reason],ensure_ascii=False).encode()).hexdigest()
    with ledger.lock,ledger.store.db:
        ledger.store.db.execute('INSERT OR IGNORE INTO funnel_events VALUES(?,?,?,?,?,?)',
            (identity,candidate,int(at),kind,reason,json.dumps(payload or {},ensure_ascii=False)))


def record_decision(ledger,decision,at):
    view=decision.get('shortHorizonV2') or {}
    candidates=view.get('candidates') or []
    gates=(view.get('env') or {}).get('gates') or {}
    if not gates:
        stage(ledger,'BTCUSDT:DATA:'+str(at//60000),at,'DATA_UNAVAILABLE',decision.get('status'),{'reasons':decision.get('reasons')})
        return
    for module in ('S1','S2','S3','S4'):
        if not any(c.get('module')==module for c in candidates):
            reason='NO_PATTERN' if gates.get(module) else 'ENVIRONMENT_CLOSED'
            stage(ledger,'BTCUSDT:'+module+':'+str(at//(300000 if module=='S3' else 900000)),at,reason,reason,{'module':module})
    for c in candidates:
        cid=c.get('candidateId') or 'BTCUSDT:'+c['module']+':'+str(c.get('confirmationTime') or at//900000)
        stage(ledger,cid,at,'DETECTED',payload={'module':c['module']})
        stage(ledger,cid,at,'SCREENED',c.get('reasonCode') or reason_code(c.get('issue')),c)
    signal=decision.get('signal')
    if signal:
        stage(ledger,signal['alert_id'],at,'EXECUTABLE',payload={'module':signal.get('module'),'ruleVersion':signal.get('rule_version')})


def report(ledger):
    with ledger.lock:
        counts=[{'stage':s,'reason':r,'count':n} for s,r,n in ledger.store.db.execute('SELECT stage,reason,count(*) FROM funnel_events GROUP BY stage,reason')]
        latest=[dict(candidateId=c,atMs=t,stage=s,reason=r) for c,t,s,r in ledger.store.db.execute('SELECT candidate_id,at_ms,stage,reason FROM funnel_events ORDER BY at_ms DESC LIMIT 30')]
    return {'countUnit':'DISTINCT_STAGE_EVENT','counts':counts,'recent':latest}


def ai_effectiveness(ledger):
    with ledger.lock:
        rows=ledger.store.db.execute('''SELECT c.ai_verdict,c.environment,l.payload FROM candidates c
          JOIN shadow_positions p ON p.candidate_id=c.id AND p.kind='SHADOW'
          JOIN labels l ON l.position_id=p.id''').fetchall()
    groups={};excluded=0
    for verdict,env,raw in rows:
        label=json.loads(raw)
        if label.get('eligibleForValidation') is not True or label.get('r') is None:
            excluded+=1;continue
        key=json.dumps(json.loads(env).get('states',{}),sort_keys=True)
        group=groups.setdefault(key,{'VETO':[],'PASS':[]})
        group['VETO' if verdict=='VETO' else 'PASS'].append(label['r'])
    return {'status':'UNVERIFIED','excludedPaths':excluded,'groups':[
        {'environment':json.loads(k),'vetoed':len(v['VETO']),'passed':len(v['PASS']),
         'vetoMeanR':sum(v['VETO'])/len(v['VETO']) if v['VETO'] else None,
         'passMeanR':sum(v['PASS'])/len(v['PASS']) if v['PASS'] else None} for k,v in groups.items()]}
