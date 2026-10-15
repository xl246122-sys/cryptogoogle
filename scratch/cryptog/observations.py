"""Persistent observation lifecycle and independent notification queue."""
import json,threading,time,uuid
class ObservationWorker(threading.Thread):
 def __init__(self,store,stop,send):
  super().__init__(daemon=True,name='observation-notifications');self.store=store;self.stop=stop;self.send=send;self.error=None;self.heartbeat=0
  with store.lock,store.db:
   store.db.executescript('CREATE TABLE IF NOT EXISTS observation_state(id TEXT PRIMARY KEY,payload TEXT); CREATE TABLE IF NOT EXISTS observation_queue(id TEXT PRIMARY KEY,payload TEXT,state TEXT,due INTEGER,expires INTEGER);')
 def update(self,s,d):
  now=s['atMs']
  with self.store.lock,self.store.db:
   row=self.store.db.execute("SELECT payload FROM observation_state WHERE id='current'").fetchone();state=json.loads(row[0]) if row else {'hour':now//3600000,'active':None,'lastEnd':0}
   def queue(kind,body):
    identity=str(uuid.uuid4());payload={'title':'Crypto-G '+kind,'body':body,'eventType':'OBSERVATION_NOTICE','eventId':identity,'expiresAt':str(now+90000)}
    self.store.db.execute('INSERT INTO observation_queue VALUES(?,?,?,?,?)',(identity,json.dumps(payload), 'PENDING',now,now+90000))
   if state['hour']!=now//3600000:
    state['hour']=now//3600000
    queue('每小时扫描摘要',('行情正常；'+('有入场候选，请打开复核' if d.get('signal') else '暂无合格入场；'+ ';'.join(d.get('reasons',[]))[:160])) if s.get('healthy') else '行情不可用，暂停新入场，请检查云端状态。')
   if s.get('healthy') and d.get('macro'):
    bars=s['series']['1m'];last=bars[-1];price=s['ticker']['bid_price'];active=state['active']
    if active:
     if now>=active['deadline'] or price<active['low']*.999:
      queue('机会失效','原观察到期或跌破支撑；停止追价，等待新结构。');state['active']=None;state['lastEnd']=now
     else:
      if last['low']<=active['low']*1.001 and now-active['created']>=180000 and not active.get('retest'):
       queue('二次探底观察','价格再次接近观察低点，尚未满足入场条件。');active['retest']=True
      checks=(d.get('research') or [{}])[0].get('checks',[])
      needed=[c['name'] for c in checks if not c['passed']]
      recovered=last['close']>max(c['high'] for c in bars[-4:-1])
      if recovered and not active.get('armed'):
       queue('条件接近','局部结构已收复，尚非买入指令；待核对：'+'、'.join(needed)[:150]);active['armed']=True
      if d.get('signal'):active['candidateSeen']=True
    elif now-state['lastEnd']>=300000:
     window=bars[-10:];drop=max((a['high']-b['low'])/a['high']*100 for i,a in enumerate(window) for b in window[i+1:])
     closes=[c['close'] for c in bars[-20:]];travel=sum(abs(b-a) for a,b in zip(closes,closes[1:]));low=min(c['low'] for c in bars[-20:]);high=max(c['high'] for c in bars[-20:])
     forming=travel>0 and abs(closes[-1]-closes[0])/travel<.35 and high>low and price<=low+(high-low)*.25
     if drop>=1 or forming:
      state['active']={'created':now,'deadline':now+3600000,'low':min(c['low'] for c in window),'armed':False}
      queue('机会观察','近10分钟急跌 %.2f%%，观察右侧恢复；尚未满足入场条件。'%drop if drop>=1 else '短周期区间下沿正在形成，观察止跌；尚未满足入场条件。')
   self.store.db.execute('INSERT OR REPLACE INTO observation_state VALUES(?,?)',('current',json.dumps(state)))
 def run(self):
  while not self.stop.is_set():
   now=int(time.time()*1000);self.heartbeat=now
   try:
    with self.store.lock,self.store.db:
     self.store.db.execute("UPDATE observation_queue SET state='EXPIRED' WHERE state='PENDING' AND expires<=?",(now,))
     row=self.store.db.execute("SELECT id,payload FROM observation_queue WHERE state='PENDING' AND due<=? ORDER BY due LIMIT 1",(now,)).fetchone()
    if row:
     p=json.loads(row[1]);ok=self.send(p['title'],p['body'],{k:str(v) for k,v in p.items() if k not in ('title','body')})
     with self.store.lock,self.store.db:self.store.db.execute('UPDATE observation_queue SET state=?,due=? WHERE id=?',('SENT' if ok else 'PENDING',now+15000,row[0]))
    self.error=None
   except Exception as exc:self.error=type(exc).__name__
   self.stop.wait(1)
