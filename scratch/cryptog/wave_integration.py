"""Research-only four-stage integration. No order execution or production BUY transport.

Detectors supply causal evidence; this layer owns lifecycle, risk, paper inventory,
and durable device delivery identities. The B experiments are NOT promoted here.
"""
import hashlib
import json
import math
import sqlite3
import threading
import time

VERSION = 'wave-state-v3-research'
PHASES = {'DOWN_START', 'SELL_EXHAUSTION', 'REBOUND_CONFIRMED', 'INVALIDATED', 'HOLDING_EXHAUSTION'}
TITLES = {'DOWN_START':'【下跌行情预警】', 'SELL_EXHAUSTION':'【超卖乏力·关注企稳】',
          'REBOUND_CONFIRMED':'【反弹确认·研究候选】', 'INVALIDATED':'【研究候选已撤销】'}


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,allow_nan=False).encode()).hexdigest()


def number(value):
    return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value)


def risk_check(plan, config, quote, now):
    """Reference-price cost mode only. Quotes may not already include added impact."""
    if not isinstance(plan,dict) or not isinstance(config,dict): return {'status':'BLOCKED','reason':'NO_REGISTERED_PLAN'}
    required=('minStopPct','maxStopPct','minNetPct','minRR','costPct','maxQuoteAgeMs','maxHoldMinutes')
    if not config.get('protocolId') or any(not number(config.get(k)) or config[k]<=0 for k in required):
        return {'status':'BLOCKED','reason':'INVALID_RESEARCH_CONFIG'}
    if config['costPct']<.24 or config['maxHoldMinutes']>360 or config['minStopPct']>config['maxStopPct']:
        return {'status':'BLOCKED','reason':'INVALID_RESEARCH_CONFIG'}
    if config.get('priceMode')!='REFERENCE_PLUS_ROUND_TRIP_COST':
        return {'status':'BLOCKED','reason':'UNSUPPORTED_COST_MODE'}
    if not isinstance(quote,dict) or not all(number(quote.get(k)) for k in ['ask','atMs']) or quote['ask']<=0:
        return {'status':'BLOCKED','reason':'QUOTE_UNAVAILABLE'}
    if not 0<=now-quote['atMs']<=config['maxQuoteAgeMs'] or quote.get('healthy') is not True:
        return {'status':'BLOCKED','reason':'QUOTE_STALE_OR_GAP'}
    if any(not number(plan.get(k)) or plan[k]<=0 for k in ['entryLow','entryHigh','stop','target','expiresAt']):
        return {'status':'BLOCKED','reason':'INVALID_PLAN'}
    if plan['expiresAt']<=now: return {'status':'BLOCKED','reason':'EXPIRED'}
    if not plan['stop']<plan['entryLow']<=plan['entryHigh']<plan['target']:
        return {'status':'BLOCKED','reason':'INVALID_STRUCTURE'}
    ask=quote['ask'];risk=(1-plan['stop']/ask)*100;net=(plan['target']/ask-1)*100-config['costPct']
    rr=net/(risk+config['costPct']) if risk+config['costPct']>0 else None
    reason=('ENTRY_RANGE' if not plan['entryLow']<=ask<=plan['entryHigh'] else
            'STOP_DISTANCE' if not config['minStopPct']-1e-9<=risk<=config['maxStopPct']+1e-9 else
            'NET_SPACE' if net<config['minNetPct'] or (config.get('strictNet') and net<=config['minNetPct']) else
            'NET_RR' if rr is None or rr<config['minRR'] else None)
    return dict(status='BLOCKED' if reason else 'PASS_RESEARCH_ONLY',reason=reason,netTargetPct=net,
                stopDistancePct=risk,netRR=rr,costPct=config['costPct'],quoteAtMs=quote['atMs'],entryReference=ask,
                costMode=config['priceMode'],protocolId=config['protocolId'])


def paper_position(actions, owner):
    """Same average-cost allocation as QUICK_PAPER_V2; buy cost reserve charged once.

    Input is the owner's confirmed journal snapshot, not signal history. Caller
    must scope actions before invoking this function. Does not append fills.
    """
    rows=[a for a in actions if a.get('strategy')=='QUICK_PAPER_V2' and a.get('recordType') in ['SIM_BUY','USER_CLOSE']]
    rows=sorted(rows,key=lambda a:(a['actedAtMs'],a['eventId']))
    qty=cost=reserve=realized=0.;seen={};cycle=None;effective=[]
    for a in rows:
        key=a['eventId']
        if key in seen:
            if seen[key]!=a: raise ValueError('CONFLICTING_FILL')
            continue
        seen[key]=a;effective.append(a)
        price=a.get('entryPrice');amount=a.get('positionSize')
        if not all(number(v) and v>0 for v in [price,amount]) or not number(a.get('actedAtMs')): raise ValueError('INVALID_PAPER_FILL')
        if a['recordType']=='SIM_BUY':
            c=a.get('costSnapshot') or {}
            if not number(c.get('frictionPct')) or c['frictionPct']<.24 or not number(c.get('applicableAtMs')) or c['applicableAtMs']>a['actedAtMs']:
                raise ValueError('UNKNOWN_PAPER_COST')
            if qty<=1e-12: cycle=key
            qty+=amount/price;cost+=amount;reserve+=amount*c['frictionPct']/100
        else:
            sold=amount/price;exit_price=a.get('exitPrice')
            if not number(exit_price) or exit_price<=0 or qty<=0 or sold>qty+1e-10: raise ValueError('INVALID_PAPER_SELL')
            if abs(price-cost/qty)>max(1e-6,price*1e-8): raise ValueError('PAPER_COST_BASIS_MISMATCH')
            fraction=min(1,sold/qty);allocated=cost*fraction;fees=reserve*fraction
            realized+=sold*exit_price-allocated-fees;qty-=sold;cost-=allocated;reserve-=fees
            if qty<1e-10: qty=cost=reserve=0.
    return dict(positionId=f'paper:{owner}:{cycle}' if cycle else None,owner=owner,revision=digest(effective),
        remainingQuantity=qty,remainingCostUsdt=cost,costReserveUsdt=reserve,realizedNetUsdt=realized,
        costVersion='paper-entry-reserve-v2',source='CONFIRMED_SIMULATION',
        latestActionMs=max((a['actedAtMs'] for a in effective),default=0))


class WaveIntegration:
    def __init__(self,path):
        self.lock=threading.RLock()
        self.db=sqlite3.connect(path,check_same_thread=False)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS wave_events(id TEXT PRIMARY KEY, parent TEXT NOT NULL, revision INTEGER NOT NULL,
                decision INTEGER NOT NULL, signature TEXT NOT NULL, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS wave_history(id TEXT NOT NULL,revision INTEGER NOT NULL,payload TEXT NOT NULL,
                PRIMARY KEY(id,revision));
            CREATE TABLE IF NOT EXISTS wave_delivery(device TEXT NOT NULL,id TEXT NOT NULL,revision INTEGER NOT NULL,
                status TEXT NOT NULL,PRIMARY KEY(device,id,revision));
            CREATE TABLE IF NOT EXISTS wave_receipts(device TEXT NOT NULL,id TEXT NOT NULL,revision INTEGER NOT NULL,
                status TEXT NOT NULL,at_ms INTEGER NOT NULL,PRIMARY KEY(device,id,revision,status));
        ''')

    def close(self): self.db.close()

    def record(self, *, event_id, parent_id, phase, decision_ms, feature_ms, evidence,
               module='REVERSAL_RESEARCH', branch='INTEGRATION', reason=None, plan=None, config=None,
               quote=None, position=None, observed_ms=None, source_revision=None):
        if phase not in PHASES or not all(isinstance(v,str) and v for v in [event_id,parent_id,module,branch]): raise ValueError('INVALID_EVENT')
        if not all(number(x) and x>0 for x in [decision_ms,feature_ms]) or feature_ms>decision_ms: raise ValueError('FUTURE_FEATURE')
        if observed_ms is not None and (not number(observed_ms) or not 0<observed_ms<=decision_ms): raise ValueError('INVALID_RECEIVE_TIME')
        if source_revision is not None and (not isinstance(source_revision,int) or isinstance(source_revision,bool) or source_revision<1):
            raise ValueError('INVALID_SOURCE_REVISION')
        if not isinstance(evidence,dict) or any(str(k).startswith('OUTCOME') for k in evidence): raise ValueError('INVALID_EVIDENCE')
        # Outcome labels cannot be hidden in nested evidence either.
        def observed_only(v):
            if isinstance(v,dict): return all(not str(k).startswith('OUTCOME') and observed_only(x) for k,x in v.items())
            if isinstance(v,list): return all(observed_only(x) for x in v)
            return not (isinstance(v,str) and v.startswith('OUTCOME_'))
        if not observed_only(evidence): raise ValueError('OUTCOME_IN_OBSERVED_EVENT')
        risk=risk_check(plan,config,quote,decision_ms) if phase=='REBOUND_CONFIRMED' else None
        title=TITLES.get(phase);position_data=None
        if phase=='HOLDING_EXHAUSTION':
            if not position or position.get('source')!='CONFIRMED_SIMULATION' or position.get('remainingQuantity',0)<=0:
                raise ValueError('NO_RECORDED_POSITION')
            if position['latestActionMs']>decision_ms: raise ValueError('FUTURE_POSITION')
            if not quote or quote.get('healthy') is not True or not all(number(quote.get(k)) for k in ['bid','atMs']) or quote['bid']<=0 or not 0<=decision_ms-quote['atMs']<=10000:
                raise ValueError('STALE_EXIT_QUOTE')
            qty=position['remainingQuantity'];cost=position['remainingCostUsdt']
            net=qty*quote['bid']-cost-position['costReserveUsdt']
            position_data=dict(position,estimatedNetUsdt=net,estimatedNetPct=net/cost*100 if cost>0 else None,bid=quote['bid'],quoteAtMs=quote['atMs'])
            title='【超买乏力·止盈提醒】' if net>0 else '【上涨乏力·风险退出提醒】'
            if evidence.get('priority') in ['STOP','INVALIDATION','TIME']:
                title='【持仓风险退出提醒】'
        safe_plan=None
        if risk and isinstance(plan,dict) and all(number(plan.get(k)) and plan[k]>0 for k in ['entryLow','entryHigh','stop','target','expiresAt']):
            if plan['stop']<plan['entryLow']<=plan['entryHigh']<plan['target']: safe_plan=plan
        core=dict(phase=phase,module=module,branch=branch,evidence=evidence,reason=reason,plan=safe_plan,
                  risk=risk,position=position_data,ruleVersion=VERSION)
        # Repeated polling is not a new notification. Dynamic quote metrics stay in the first immutable snapshot.
        signature=digest(dict(phase=phase,module=module,branch=branch,reason=reason,plan=core['plan'],
            riskStatus=risk['status'] if risk else None,riskReason=risk['reason'] if risk else None,
            evidenceKey=evidence.get('stateKey',digest(evidence)),
            positionRevision=position['revision'] if position else None,
            holdingWording=title if phase=='HOLDING_EXHAUSTION' else None))
        with self.lock,self.db:
            row=self.db.execute('SELECT parent,revision,decision,signature,payload FROM wave_events WHERE id=?',(event_id,)).fetchone()
            if row:
                if row[0]!=parent_id: raise ValueError('EVENT_PARENT_CONFLICT')
                previous=json.loads(row[4])
                if previous['position'] and (not position or previous['position']['owner']!=position['owner']):
                    raise ValueError('POSITION_OWNER_MISMATCH')
                if decision_ms<row[2]: raise ValueError('OUT_OF_ORDER_EVENT')
                if row[3]==signature: return json.loads(row[4])
                if decision_ms==row[2] and (source_revision is None or source_revision<=(previous.get('sourceRevision') or 0)):
                    raise ValueError('CONFLICTING_EVENT_TIME')
                if previous['lifecycle']=='INVALIDATED': raise ValueError('TERMINAL_EVENT_REQUIRES_NEW_ID')
            revision=row[1]+1 if row else 1
            payload=dict(core,eventType='WAVE_STATE_RESEARCH',eventId=event_id,parentEventId=parent_id,revision=revision,
                symbol='BTCUSDT',signalType='OBSERVE',tier='RESEARCH',tradeEligible=False,title=title,
                issuedAtMs=decision_ms,decisionTime=decision_ms,featureAsOfTime=feature_ms,receivedTime=observed_ms,
                sourceRevision=source_revision,
                lifecycle='INVALIDATED' if phase=='INVALIDATED' else 'ACTIVE',
                body='研究联调记录，未经收益验证；不代表已买入或已卖出。',expiresAt=safe_plan.get('expiresAt') if safe_plan else None)
            encoded=json.dumps(payload,ensure_ascii=False,allow_nan=False)
            self.db.execute('INSERT OR REPLACE INTO wave_events VALUES(?,?,?,?,?,?)',(event_id,parent_id,revision,decision_ms,signature,encoded))
            self.db.execute('INSERT INTO wave_history VALUES(?,?,?)',(event_id,revision,encoded))
            return payload

    def messages(self,owner=None):
        with self.lock:
            rows=[json.loads(r[0]) for r in self.db.execute('SELECT payload FROM wave_events ORDER BY decision DESC LIMIT 200')]
        # Never expose another owner's position through public market-state.
        return [p for p in rows if p['position'] is None or (owner is not None and p['position']['owner']==owner)]

    def expire(self,now):
        """Keep history while invalidating plans; never relabel an expired plan BUY."""
        with self.lock:
            for p in self.messages():
                if p['phase']=='REBOUND_CONFIRMED' and number(p['expiresAt']) and p['expiresAt']<=now:
                    self.record(event_id=p['eventId'],parent_id=p['parentEventId'],phase='INVALIDATED',
                        decision_ms=max(now,p['decisionTime']+1),feature_ms=p['featureAsOfTime'],
                        evidence={'stateKey':'EXPIRED'},reason='EXPIRED',module=p['module'],branch=p['branch'])

    def delivery_payload(self,event_id,revision,now,quote,config):
        """Recheck before a test transport. This module deliberately has no FCM sender."""
        with self.lock:
            row=self.db.execute('SELECT payload FROM wave_events WHERE id=?',(event_id,)).fetchone()
        if not row: raise ValueError('UNKNOWN_EVENT')
        p=json.loads(row[0])
        if p['revision']!=revision or p['lifecycle']=='INVALIDATED': raise ValueError('STALE_DELIVERY_REVISION')
        if p['phase']=='REBOUND_CONFIRMED':
            checked=risk_check(p['plan'],config,quote,now)
            if checked['status']!='PASS_RESEARCH_ONLY': raise ValueError('DELIVERY_RISK_REJECTED:'+str(checked['reason']))
            p=dict(p,deliveryRisk=checked)
        return p

    def observe_paper(self,actions,owner,*,event_id,parent_id,decision_ms,feature_ms,evidence,quote):
        position=paper_position(actions,owner)
        if position['remainingQuantity']<=0:
            with self.lock:
                row=self.db.execute('SELECT payload FROM wave_events WHERE id=?',(event_id,)).fetchone()
            if row and json.loads(row[0])['phase']=='HOLDING_EXHAUSTION' and json.loads(row[0])['lifecycle']=='ACTIVE':
                old=json.loads(row[0])
                if old['position']['owner']!=owner: raise ValueError('POSITION_OWNER_MISMATCH')
                if decision_ms<=old['decisionTime'] or position['latestActionMs']>decision_ms: raise ValueError('OUT_OF_ORDER_POSITION')
                # Preserve private ownership even after the position has closed.
                with self.lock,self.db:
                    old.update(revision=old['revision']+1,decisionTime=decision_ms,issuedAtMs=decision_ms,
                        lifecycle='INVALIDATED',reason='POSITION_CLOSED',title='【持仓已结束·提醒失效】')
                    old['position'].update(position)
                    encoded=json.dumps(old,ensure_ascii=False,allow_nan=False)
                    self.db.execute('UPDATE wave_events SET revision=?,decision=?,signature=?,payload=? WHERE id=?',
                        (old['revision'],decision_ms,digest(old),encoded,event_id))
                    self.db.execute('INSERT INTO wave_history VALUES(?,?,?)',(event_id,old['revision'],encoded))
            return None
        return self.record(event_id=event_id,parent_id=parent_id,phase='HOLDING_EXHAUSTION',decision_ms=decision_ms,
            feature_ms=feature_ms,evidence=evidence,quote=quote,position=position)

    def enqueue(self,device,event_id,revision,*,owner=None):
        if not isinstance(device,str) or not device: raise ValueError('INVALID_DEVICE')
        with self.lock,self.db:
            row=self.db.execute('SELECT revision,payload FROM wave_events WHERE id=?',(event_id,)).fetchone()
            if not row or row[0]!=revision: raise ValueError('STALE_DELIVERY_REVISION')
            p=json.loads(row[1])
            if p['position'] and owner!=p['position']['owner']: raise ValueError('POSITION_OWNER_MISMATCH')
            changed=self.db.execute('INSERT OR IGNORE INTO wave_delivery VALUES(?,?,?,?)',(device,event_id,revision,'QUEUED')).rowcount
            return bool(changed)

    def receipt(self,device,event_id,revision,status):
        order=['QUEUED','PLATFORM_ACCEPTED','RECEIVED','DISPLAYED','OPENED']
        if status not in order: raise ValueError('INVALID_RECEIPT')
        with self.lock,self.db:
            row=self.db.execute('SELECT status FROM wave_delivery WHERE device=? AND id=? AND revision=?',(device,event_id,revision)).fetchone()
            if not row: raise ValueError('UNKNOWN_DELIVERY')
            latest=order[max(order.index(row[0]),order.index(status))]
            self.db.execute('UPDATE wave_delivery SET status=? WHERE device=? AND id=? AND revision=?',(latest,device,event_id,revision))
            self.db.execute('INSERT OR IGNORE INTO wave_receipts VALUES(?,?,?,?,?)',(device,event_id,revision,status,int(time.time()*1000)))
            return latest
