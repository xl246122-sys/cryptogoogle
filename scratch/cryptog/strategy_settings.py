"""Shared owner strategy-family settings. Stored transactionally, revision checked."""
import json
KEYS=('BURST_BREAKOUT','FLASH_CRASH_REBOUND','RANGE_OSCILLATION')
class StrategySettings:
 def __init__(self,store):
  self.store=store
  with store.lock,store.db:store.db.execute('CREATE TABLE IF NOT EXISTS strategy_settings(id INTEGER PRIMARY KEY,payload TEXT)')
 def get(self):
  with self.store.lock:
   r=self.store.db.execute('SELECT payload FROM strategy_settings WHERE id=1').fetchone()
   return json.loads(r[0]) if r else {'revision':0,'activeStrategies':dict.fromkeys(KEYS,True)}
 def put(self,p):
  flags=p.get('activeStrategies',{})
  if set(flags)!=set(KEYS) or any(type(v)!=bool for v in flags.values()):raise ValueError('Invalid strategy families')
  with self.store.lock,self.store.db:
   old=self.get()
   if p.get('revision')!=old['revision']:raise ValueError('Configuration changed; refresh and retry')
   value={'revision':old['revision']+1,'activeStrategies':flags}
   self.store.db.execute('INSERT OR REPLACE INTO strategy_settings VALUES(1,?)',(json.dumps(value),));return value
