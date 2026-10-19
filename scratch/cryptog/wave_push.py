"""Private research notifications; no promotion, order or strategy mutation."""
import hashlib
import json
import sqlite3
from .wave_integration import risk_check

LABEL='研究观察·未验证'
ALIASES={'B-R05':'B-R00','B-R06':'B-R00'} # Identical entry events; exits are NOT user positions.
PHASE_ORDER={'DOWN_START':1,'SELL_EXHAUSTION':2,'REBOUND_CONFIRMED':3,'INVALIDATED':4}

def encode(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,allow_nan=False)

def quote_for_risk(q,now):
    if not q or not q.get('healthy') or not 0<=now-q.get('observedMs',0)<=5000:
        return None
    return dict(ask=q['ask'],bid=q['bid'],atMs=q['sourceMs']-q['clockOffsetMs'],healthy=True)

def payload_from_event(event,feature_ms,decision_ms,now):
    phase=event['phase']
    if phase not in PHASE_ORDER or not 0<=now-feature_ms<=120000:
        raise ValueError('UNSUPPORTED_OR_STALE_EVENT')
    group=ALIASES.get(event['group'],event['group'])
    if group not in ['B-R00','B-R01','B-R02','B-R03','B-R04']:
        raise ValueError('UNREGISTERED_GROUP')
    original=event['eventId'].split(':')
    if len(original)!=3 or original[0]!=event['group'] or int(original[1])!=event['window']:
        raise ValueError('INVALID_SOURCE_ID')
    trigger=int(original[2])
    if not trigger<feature_ms<=decision_ms<=now:
        raise ValueError('NONCAUSAL_EVENT')
    identity=f'wave-live:{group}:{event["window"]}:{trigger}'
    # Epoch-derived revision is stable through restart and input replay, under JS integer limit.
    revision=feature_ms*10+PHASE_ORDER[phase]
    plan=None;config=None;risk=None
    if phase=='REBOUND_CONFIRMED':
        p=event['plan']
        plan={k:p[k] for k in ['entryLow','entryHigh','stop','target']}
        plan['expiresAt']=feature_ms+180000
        config=dict(protocolId='WAVE-D-20261018-002',minStopPct=.35,maxStopPct=1.2,
            minNetPct=p['minNet'],strictNet=p['window']>15,minRR=1.2,costPct=.24,
            maxQuoteAgeMs=5000,maxHoldMinutes=p['holdMinutes'],priceMode='REFERENCE_PLUS_ROUND_TRIP_COST')
        risk=dict(status='BLOCKED',reason='AWAITING_SEND_RECHECK')
    data=dict(eventType='WAVE_STATE_RESEARCH',ruleVersion='wave-state-v3-research',
        eventId=identity,parentEventId=f'wave-live:{group}:{trigger}',revision=revision,
        symbol='BTCUSDT',module='REVERSAL_RESEARCH',branch=group,phase=phase,
        signalType='OBSERVE',tier='RESEARCH',tradeEligible=False,
        issuedAtMs=decision_ms,decisionTime=decision_ms,featureAsOfTime=feature_ms,
        lifecycle='INVALIDATED' if phase=='INVALIDATED' else 'ACTIVE',reason=event.get('reason'),
        evidence=dict(label=LABEL,experiment='WAVE-D-20261018-002',windowMinutes=event['window'],
            source='LIVE_SHADOW_EVENT',sourceEvidence=event.get('evidence') or {}),
        plan=plan,risk=risk,position=None,expiresAt=plan['expiresAt'] if plan else feature_ms+120000)
    return data,config

def recheck(data,config,quote,now):
    if data['expiresAt']<=now:raise ValueError('EXPIRED')
    if data['phase']=='HOLDING_EXHAUSTION' and data['lifecycle']=='INVALIDATED':return data
    current=quote_for_risk(quote,now)
    if current is None:raise ValueError('QUOTE_NOT_FRESH')
    if data['phase']=='HOLDING_EXHAUSTION':
        if not 0<=now-current['atMs']<=5000:raise ValueError('QUOTE_NOT_FRESH')
        p=dict(data['position']);net=p['remainingQuantity']*current['bid']-p['remainingCostUsdt']-p['costReserveUsdt']
        p.update(estimatedNetUsdt=net,estimatedNetPct=net/p['remainingCostUsdt']*100,bid=current['bid'],quoteAtMs=current['atMs'])
        data=dict(data,position=p)
    if data['phase']=='REBOUND_CONFIRMED':
        checked=risk_check(data['plan'],config,current,now)
        if checked['status']!='PASS_RESEARCH_ONLY':raise ValueError('RISK_'+str(checked['reason']))
        data=dict(data,risk=checked)
    return data

def transport_fields(data):
    phase=data['phase']
    if phase=='HOLDING_EXHAUSTION':
        p=data['position'];closed=data['lifecycle']=='INVALIDATED'
        title='【'+LABEL+'】'+('模拟持仓已结束·提醒失效' if closed else '超买乏力·考虑获利了结' if p['estimatedNetUsdt']>0 else '上涨乏力·注意回撤风险')
        body='模拟仓提醒，不会自动卖出。'
        if not closed:body+=f"剩余 {p['remainingQuantity']:.8f} BTC；按当前买一价和买入成本预算估计，扣费后盈亏 {p['estimatedNetUsdt']:+.2f} USDT（{p['estimatedNetPct']:+.2f}%）。请自行核对退出。"
        fields={k:(encode(v) if not isinstance(v,str) else v) for k,v in data.items()}
        fields.update(title=title,body=body)
        if sum(len(k.encode())+len(v.encode()) for k,v in fields.items())>3500:raise ValueError('PAYLOAD_TOO_LARGE')
        return title,body,fields
    title='【'+LABEL+'】'+{'DOWN_START':'下跌启动，注意盯盘','SELL_EXHAUSTION':'超卖乏力，关注企稳',
        'REBOUND_CONFIRMED':'反弹确认·研究候选','INVALIDATED':'研究候选已撤销'}[phase]
    body='仅供研究观察，不是正式买入指令，不代表已成交。'
    if phase=='REBOUND_CONFIRMED':
        r=data['risk'];p=data['plan']
        body+=f"参考区间 {p['entryLow']:.2f}–{p['entryHigh']:.2f}；预计扣费净空间 {r['netTargetPct']:.2f}%（非保证收益），止损距离 {r['stopDistancePct']:.2f}%。"
    else:body+='打开查看事件详情与状态。'
    fields={k:(encode(v) if not isinstance(v,str) else v) for k,v in data.items()}
    fields.update(title=title,body=body)
    if sum(len(k.encode())+len(v.encode()) for k,v in fields.items())>3500:
        raise ValueError('PAYLOAD_TOO_LARGE')
    return title,body,fields


class ResearchOutbox:
    def __init__(self,path):
        self.db=sqlite3.connect(path,timeout=10)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.executescript('''
          CREATE TABLE IF NOT EXISTS deliveries(id TEXT PRIMARY KEY,event TEXT,revision INTEGER,
            feature_ms INTEGER,payload TEXT,config TEXT,state TEXT,at_ms INTEGER,result TEXT);
          CREATE TABLE IF NOT EXISTS cursor(name TEXT PRIMARY KEY,value TEXT);
          CREATE INDEX IF NOT EXISTS delivery_state ON deliveries(state,feature_ms);
        ''')
        # An interrupted send might have reached FCM. Never silently send it twice.
        with self.db:self.db.execute("UPDATE deliveries SET state='UNCERTAIN',result='PROCESS_RESTART_DURING_SEND' WHERE state='SENDING'")

    def get(self,key,default=None):
        row=self.db.execute('SELECT value FROM cursor WHERE name=?',(key,)).fetchone()
        return json.loads(row[0]) if row else default

    def put(self,key,value):
        with self.db:self.db.execute('INSERT OR REPLACE INTO cursor VALUES(?,?)',(key,encode(value)))

    def ingest(self,data,config,now):
        key=hashlib.sha256(f"{data['eventId']}:{data['revision']}".encode()).hexdigest()
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO deliveries VALUES(?,?,?,?,?,?, 'PENDING',?,NULL)",
                (key,data['eventId'],data['revision'],data['featureAsOfTime'],encode(data),encode(config),now))
            self.db.execute("UPDATE deliveries SET state='SUPERSEDED' WHERE event=? AND revision<? AND state='PENDING'",
                (data['eventId'],data['revision']))
            self.db.execute("UPDATE deliveries SET state='SUPERSEDED' WHERE event=? AND state='PENDING' AND revision<(SELECT max(revision) FROM deliveries WHERE event=?)",
                (data['eventId'],data['eventId']))
        return key

    def step(self,quote,now,send):
        # One new observation per 30 seconds. Expired backlog is discarded, never replayed on restart.
        with self.db:
            self.db.execute("UPDATE deliveries SET state='EXPIRED' WHERE state='PENDING' AND json_extract(payload,'$.expiresAt')<=?",(now,))
        if now-self.get('lastAttemptMs',0)<30000:return None
        row=self.db.execute("SELECT id,payload,config FROM deliveries WHERE state='PENDING' ORDER BY feature_ms DESC,revision DESC LIMIT 1").fetchone()
        if not row:return None
        key,text,config=row;data=json.loads(text)
        if data['lifecycle']=='INVALIDATED' and not self.db.execute("SELECT 1 FROM deliveries WHERE event=? AND state='FCM_ACCEPTED' LIMIT 1",(data['eventId'],)).fetchone():
            with self.db:self.db.execute("UPDATE deliveries SET state='NO_PRIOR_NOTIFICATION' WHERE id=?",(key,))
            return None
        try:data=recheck(data,json.loads(config),quote,now)
        except (ValueError,KeyError,TypeError) as error:
            # Quote outages can recover inside TTL; risk failures are recorded, not BUY pushes.
            if str(error)=='QUOTE_NOT_FRESH':return None
            with self.db:self.db.execute("UPDATE deliveries SET state='BLOCKED',result=? WHERE id=?",(str(error),key))
            return None
        with self.db:
            self.db.execute("UPDATE deliveries SET state='SENDING',payload=?,at_ms=? WHERE id=?",(encode(data),now,key))
            self.db.execute('INSERT OR REPLACE INTO cursor VALUES(?,?)',('lastAttemptMs',encode(now)))
        try:
            result=send(data)
            state='FCM_ACCEPTED'
        except Exception as error:
            result=type(error).__name__;state='UNCERTAIN'
        with self.db:self.db.execute('UPDATE deliveries SET state=?,result=? WHERE id=?',(state,result,key))
        return dict(id=key,state=state)
