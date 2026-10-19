"""Owner-scoped paper inventory and research E1 exhaustion; never executes exits."""
import bisect
import hashlib
import json
import math
from .indicators import rsi_series
from .wave_integration import paper_position
from .wave_push import quote_for_risk

DAY=86400000

def owned_actions(path,owner,legacy_ids=()):
    rows=[];seen={}
    raw=path.read_bytes()
    # An append in progress is not a confirmed action snapshot.
    if raw and not raw.endswith(b'\n'):raise ValueError('ACTION_APPEND_IN_PROGRESS')
    for line in raw.splitlines():
        if not line.strip():continue
        row=json.loads(line)
        if row.get('strategy')!='QUICK_PAPER_V2':continue
        if row.get('authenticatedOwner')!=owner and not (not row.get('authenticatedOwner') and row.get('eventId') in legacy_ids):continue
        key=row['eventId']
        if key in seen and seen[key]!=row:raise ValueError('CONFLICTING_ACTION')
        if key not in seen:rows.append(row);seen[key]=row
    return rows

def exhaustion(rows,opened_ms,now):
    """E1: past 90-day daily-frozen RSI p90, then two falls and prior-low break."""
    if not rows:raise ValueError('BARS_UNAVAILABLE')
    times=[r[0] for r in rows];last=times[-1]+60000
    if not 0<=now-last<=120000:raise ValueError('BARS_STALE')
    if any(b-a!=60000 for a,b in zip(times,times[1:])):raise ValueError('MINUTE_GAP')
    if any(not all(math.isfinite(v) for v in r[:5]) or not 0<r[3]<=min(r[1],r[4])<=max(r[1],r[4])<=r[2] for r in rows):
        raise ValueError('INVALID_BARS')
    boundary=times[-1]//DAY*DAY
    end=bisect.bisect_left(times,boundary);begin=bisect.bisect_left(times,boundary-90*DAY)
    rsi=rsi_series([r[4] for r in rows],14)
    train=rsi[begin:end]
    if len(train)!=90*1440 or any(x is None for x in train):raise ValueError('CALIBRATION_INCOMPLETE')
    values=sorted(train);at=(len(values)-1)*.9;lo=int(at)
    threshold=values[lo]+(values[min(lo+1,len(values)-1)]-values[lo])*(at-lo)
    k=bisect.bisect_left(times,opened_ms//60000*60000);j=len(rows)-1
    signal=j>=k+2 and any(x>threshold for x in rsi[max(k,j-4):j+1]) and rsi[j]<rsi[j-1]<rsi[j-2] and rows[j][4]<rows[j-1][3]
    return dict(triggered=bool(signal),featureMs=last,rsi90=threshold,rsi14=rsi[-1],
        trainingEndExclusiveMs=boundary,rule='E1_RESEARCH_RSI_P90_TURN_AND_LOW_BREAK')

def position_snapshot(actions,owner,now):
    if any(a['actedAtMs']>now for a in actions):raise ValueError('FUTURE_ACTION')
    p=paper_position(actions,owner)
    if p['positionId']:
        cycle=p['positionId'].split(':',2)[2]
        p['openedMs']=next(a['actedAtMs'] for a in actions if a['eventId']==cycle)
    return p

def holding_payload(position,evidence,quote,now,event_id,revision,closed=False):
    p=dict(position)
    if closed:
        p.update(remainingQuantity=0.,remainingCostUsdt=0.,costReserveUsdt=0.,estimatedNetUsdt=0.,estimatedNetPct=None,bid=0.)
    else:
        q=quote_for_risk(quote,now)
        if not q or not 0<=now-q['atMs']<=5000:raise ValueError('QUOTE_NOT_FRESH')
        net=p['remainingQuantity']*q['bid']-p['remainingCostUsdt']-p['costReserveUsdt']
        p.update(estimatedNetUsdt=net,estimatedNetPct=net/p['remainingCostUsdt']*100,bid=q['bid'],quoteAtMs=q['atMs'])
    # Never transmit bearer hashes or the action journal itself.
    p.pop('owner',None)
    p['positionId']='paper:'+hashlib.sha256(position['positionId'].encode()).hexdigest()[:24]
    return dict(eventType='WAVE_STATE_RESEARCH',ruleVersion='wave-state-v3-research',
        eventId=event_id,parentEventId='holding:'+hashlib.sha256(position['positionId'].encode()).hexdigest()[:24],
        revision=revision,phase='HOLDING_EXHAUSTION',symbol='BTCUSDT',module='PAPER_HOLDING',branch='E1',
        signalType='OBSERVE',tier='RESEARCH',tradeEligible=False,issuedAtMs=now,decisionTime=now,
        featureAsOfTime=evidence['featureMs'],lifecycle='INVALIDATED' if closed else 'ACTIVE',
        reason='POSITION_CLOSED' if closed else None,expiresAt=now+120000,
        evidence=dict(evidence,label='研究观察·未验证',source='OWNER_CONFIRMED_PAPER_JOURNAL'),position=p,plan=None,risk=None)

class HoldingMonitor:
    def __init__(self,outbox,source):
        self.outbox=outbox;self.source=source;self.cache_key=None;self.cached=None

    def tick(self,actions,owner,quote,now):
        p=position_snapshot(actions,owner,now)
        tracked=self.outbox.get('holdingTracked',{})
        # Close notices are processed before data availability or new exhaustion.
        for identity,old in list(tracked.items()):
            if not old.get('closed') and (p['remainingQuantity']<=0 or old['position']['positionId']!=p['positionId']):
                closed=dict(old['position'],revision=p['revision'],latestActionMs=p['latestActionMs'])
                data=holding_payload(closed,old['evidence'],quote,now,identity,now*10+4,True)
                self.outbox.ingest(data,None,now);old['closed']=True
        self.outbox.put('holdingTracked',tracked)
        if p['remainingQuantity']<=0:return dict(state='NO_OPEN_PAPER_POSITION',quantity=0)
        latest=self.source.execute('SELECT max(time) FROM bars WHERE time+60000<=?',(now,)).fetchone()[0]
        key=(latest,p['openedMs'])
        if key!=self.cache_key:
            boundary=(latest or now)//DAY*DAY
            rows=self.source.execute('SELECT time,open,high,low,close FROM bars WHERE time>=? AND time+60000<=? ORDER BY time',(boundary-92*DAY,now)).fetchall()
            self.cached=exhaustion(rows,p['openedMs'],now);self.cache_key=key
        ev=self.cached
        if not 0<=now-ev['featureMs']<=120000:raise ValueError('BARS_STALE')
        episode=self.outbox.get('holdingEpisode')
        if not ev['triggered']:
            self.outbox.put('holdingEpisode',None)
            return dict(state='MONITORING',quantity=p['remainingQuantity'],featureMs=ev['featureMs'])
        if not episode or episode['cycle']!=p['positionId']:
            identity='holding-live:'+hashlib.sha256((p['positionId']+':'+str(ev['featureMs'])).encode()).hexdigest()[:32]
            episode=dict(cycle=p['positionId'],id=identity,signature=None)
        signature=p['revision']
        if episode['signature']!=signature:
            data=holding_payload(p,ev,quote,now,episode['id'],now*10+3)
            self.outbox.ingest(data,None,now)
            tracked[episode['id']]=dict(position=p,evidence=ev,closed=False)
            self.outbox.put('holdingTracked',tracked)
            episode['signature']=signature;self.outbox.put('holdingEpisode',episode)
        return dict(state='EXHAUSTION_OBSERVED',quantity=p['remainingQuantity'],featureMs=ev['featureMs'])
