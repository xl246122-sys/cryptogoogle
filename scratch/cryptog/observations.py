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
   # Old observation-only deliveries are never replayed after upgrade.
   self.store.db.execute("UPDATE observation_queue SET state='CANCELLED' WHERE state='PENDING' AND json_extract(payload,'$.eventType')='OBSERVATION_NOTICE'")
   row=self.store.db.execute("SELECT payload FROM observation_state WHERE id='quiet-v1'").fetchone()
   state=json.loads(row[0]) if row else {'lastPrepare':0,'active':None}
   active=state['active']
   if active and (d.get('signal') or not s.get('healthy') or not any(r.get('preparation') for r in d.get('research',[])) or now>=active['expires'] or (s.get('healthy') and s['ticker']['bid_price']<=active['stop'])):
    row=self.store.db.execute('SELECT payload FROM observation_queue WHERE id=?',(active['id'],)).fetchone()
    if row:
     payload=json.loads(row[0]);payload.update(body='准备条件已失效，等待新结构。',lifecycle='EXPIRED')
     self.store.db.execute("UPDATE observation_queue SET payload=?,state=CASE WHEN state='PENDING' THEN 'CANCELLED' ELSE state END WHERE id=?",(json.dumps(payload),active['id']))
    state['active']=None
   if getattr(self,'prepare_enabled',True) and s.get('healthy') and not state['active'] and not d.get('signal') and now-state['lastPrepare']>=1800000:
    for research in d.get('research',[]):
     plan=research.get('preparation')
     if not plan: continue
     identity='PREP_'+str(now)
     payload={'eventId':identity,'eventType':'PREPARE_ENTRY','title':'Crypto-G 准备入场（尚未确认）',
      'body':research['label']+'；仅待：'+plan['waiting']+'。尚非买入指令。',
      'timestamp':str(now),'expiresAt':str(now+90000),'opportunityId':identity,
      'targetTP1':str(plan['targetTP1']),'stopLoss':str(plan['stopLoss'])}
     self.store.db.execute('INSERT INTO observation_queue VALUES(?,?,?,?,?)',(identity,json.dumps(payload),'PENDING',now,now+90000))
     state.update(lastPrepare=now,active={'id':identity,'stop':plan['stopLoss'],'expires':now+90000})
     break
   # Only delivered entries can produce an entry-invalidated notice. Mere preparation cannot.
   for identity,updated in self.store.db.execute("SELECT o.id,o.updated_ms FROM opportunities o JOIN outbox b ON b.id=o.id WHERE o.state='INVALIDATED' AND b.state='SENT' AND o.updated_ms>?",(now-90000,)).fetchall():
    key='LEAVE_'+identity
    payload={'eventId':key,'eventType':'ENTRY_INVALIDATED','opportunityId':identity,'title':'Crypto-G 离场 · 入场机会失效',
      'body':'原BTC入场条件已失效，请勿继续按原信号入场；不代表已确认持仓或UNI/SUI卖出指令。','timestamp':str(updated),'expiresAt':str(updated+90000)}
    self.store.db.execute('INSERT OR IGNORE INTO observation_queue VALUES(?,?,?,?,?)',(key,json.dumps(payload),'PENDING',now,updated+90000))
   self.store.db.execute('INSERT OR REPLACE INTO observation_state VALUES(?,?)',('quiet-v1',json.dumps(state)))
 def health(self, now):
  with self.store.lock,self.store.db:
   pending=self.store.db.execute("SELECT count(*) FROM observation_queue WHERE state='PENDING'").fetchone()[0]
   expired=self.store.db.execute("SELECT count(*) FROM observation_queue WHERE state='EXPIRED'").fetchone()[0]
   sent=self.store.db.execute("SELECT count(*) FROM observation_queue WHERE state='SENT'").fetchone()[0]
  return {'healthy':self.is_alive() and bool(self.heartbeat and now-self.heartbeat<=10000),
          'error':self.error,'pending':pending,'expired':expired,'sent':sent}
 def run(self):
  while not self.stop.is_set():
   now=int(time.time()*1000);self.heartbeat=now
   try:
    with self.store.lock,self.store.db:
     self.store.db.execute("UPDATE observation_queue SET state='EXPIRED' WHERE state='PENDING' AND expires<=?",(now,))
     row=self.store.db.execute("SELECT id,payload FROM observation_queue WHERE state='PENDING' AND due<=? ORDER BY due LIMIT 1",(now,)).fetchone()
    if row:
     p=json.loads(row[1])
     if p.get('eventType') not in ('PREPARE_ENTRY','ENTRY_INVALIDATED'):
      with self.store.lock,self.store.db:self.store.db.execute("UPDATE observation_queue SET state='CANCELLED' WHERE id=?",(row[0],))
      continue
     if p['eventType']=='PREPARE_ENTRY' and hasattr(self,'cache'):
      snapshot=self.cache.snapshot(now);q=snapshot.get('ticker',{});ask=q.get('ask_price',0);bid=q.get('bid_price',0)
      tp=float(p['targetTP1']);sl=float(p['stopLoss'])
      net=(tp/ask-1)*100-.11 if ask else -1; risk=(1-sl/ask)*100+.11 if ask else 0
      if not snapshot.get('healthy') or not 0<sl<bid<ask<tp or (ask-bid)/ask*100>.02 or net<.59-1e-9 or risk<=0 or net/risk<1.1:
       with self.store.lock,self.store.db:self.store.db.execute("UPDATE observation_queue SET state='CANCELLED' WHERE id=?",(row[0],))
       continue
     ok=self.send(p['title'],p['body'],{k:str(v) for k,v in p.items()})
     with self.store.lock,self.store.db:self.store.db.execute('UPDATE observation_queue SET state=?,due=? WHERE id=?',('SENT' if ok else 'PENDING',now+15000,row[0]))
    self.error=None
   except Exception as exc:self.error=type(exc).__name__
   self.stop.wait(1)
