"""Independent real-time BTC event stages. No LLM on the critical path."""
import json
import math
import threading
import time
from .ai_policy import target_evidence


def fast_setup(snapshot):
    if not snapshot.get('healthy'): return None
    now=snapshot['atMs'];trades=snapshot.get('recentTrades',[])
    if len(trades)<4 or not 0<=now-trades[-1]['atMs']<=2000: return None
    if any(not math.isfinite(t['price']) or t['price']<=0 or not math.isfinite(t['quantity']) or t['quantity']<=0 for t in trades): return None
    if any(b['atMs']<a['atMs'] or b['id']!=a['id']+1 for a,b in zip(trades,trades[1:])): return None
    chosen=None
    for seconds in (10,30,60,180,300):
        window=[t for t in trades if now-seconds*1000<=t['atMs']<=now]
        if len(window)<4 or window[0]['atMs']>now-seconds*1000+2000: continue
        peak=max(range(len(window)),key=lambda i:window[i]['price'])
        tail=window[peak:]
        low=min(t['price'] for t in tail);high=window[peak]['price']
        drop=(high-low)/high*100
        if 1<=drop<=10:
            chosen=(window,low,high,drop,seconds,window[peak]['id']);break
    if not chosen: return None
    window,low,high,drop,seconds,peak_id=chosen
    recent=[t for t in window if t['atMs']>=now-3000]
    prior=[t for t in window if now-6000<=t['atMs']<now-3000]
    stable=bool(recent and prior and min(t['price'] for t in recent)>=min(t['price'] for t in prior))
    sell=lambda rows:sum(t['quantity'] for t in rows if t['buyerMaker'])
    volume=sum(t['quantity'] for t in recent)
    buy_ratio=sum(t['quantity'] for t in recent if not t['buyerMaker'])/volume if volume else 0
    ask=snapshot['ticker']['ask_price'];bid=snapshot['ticker']['bid_price']
    reclaim=ask>=low*1.0015
    # Five explicit reversal gates: ceased lows, reclaim, executed buying,
    # weakening selling, and clean spread. Target/R:R are checked again by AIEngine.
    gates=(stable,reclaim,buy_ratio>=.55,bool(prior) and sell(recent)<sell(prior),0<(ask-bid)/ask*100<=.02)
    stage='STABILIZING' if stable and gates[3] else 'MARKET_EVENT'
    result=dict(stage=stage,low=low,high=high,dropPct=drop,windowSeconds=seconds,gates=gates,eventKey='FAST_'+str(peak_id))
    if not all(gates): return result
    bars=snapshot.get('series',{}).get('1m',[])
    anchors=[b for b in bars[-5:] if b.get('is_closed') and b['close_time']<now and b['low']<ask]
    if not anchors:return result
    anchor=min(anchors,key=lambda b:abs(b['low']-low))
    stop=min(low,anchor['low'])*.9995
    # Use actual confirmed resistance, never synthesize a profitable target.
    try:
        evidence=target_evidence(snapshot,ask,ask*1.00001,ask*1.00001,'FLASH_REBOUND_FAST')
    except ValueError:return result
    target=math.floor(min(high,evidence['targetResistance1'])*.9995*100)/100
    result['decision']=dict(is_buy=True,scenario='FLASH_REBOUND_FAST',entry_min=ask*.999,
        entry_max=ask*1.0005,target_tp1=target,target_tp2=target,stop_loss=stop,
        hold_minutes=10,hold_seconds=600,anchor_timeframe='1m',anchor_time_ms=anchor['time'],
        summary_zh='急跌后卖压减弱，低点收复')
    return result


class AIFastWorker(threading.Thread):
    def __init__(self,ai,stop):
        super().__init__(name='btc-ai-fast',daemon=True)
        self.ai,self.stop=ai,stop
        self.heartbeat_ms=0;self.error=None
        self.last_attempt=0
        with ai.store.lock,ai.store.db:
            ai.store.db.execute('CREATE TABLE IF NOT EXISTS ai_fast_episode (id INTEGER PRIMARY KEY, started INTEGER, seen INTEGER)')

    def step(self):
        now=int(time.time()*1000);self.heartbeat_ms=now
        if not self.ai.get_config().get('enabled'):return
        snapshot=self.ai.cache.fast_snapshot(now)
        event=fast_setup(snapshot)
        if not event:return
        # One persistent episode until five minutes without a qualifying shock.
        # Rolling peak movement must not create a notification every half second.
        with self.ai.store.lock,self.ai.store.db:
            row=self.ai.store.db.execute('SELECT started,seen FROM ai_fast_episode WHERE id=1').fetchone()
            started=row[0] if row and 0<=now-row[1]<=300000 else now
            self.ai.store.db.execute('INSERT OR REPLACE INTO ai_fast_episode VALUES(1,?,?)',(started,now))
        key='FAST_'+str(started)
        self.ai.publish_stage(key,event['stage'],f"{event['windowSeconds']}秒窗口下跌{event['dropPct']:.2f}%，"+('等待企稳' if event['stage']=='MARKET_EVENT' else '卖压减弱，等待买入复核'),now)
        # 10秒到5分钟的回弹不推送到手机。10分钟到4小时的买点只走 short_horizon。

    def run(self):
        while not self.stop.is_set():
            try:self.step();self.error=None
            except Exception as exc:self.error=type(exc).__name__
            self.stop.wait(.5)
