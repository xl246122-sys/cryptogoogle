import sqlite3,json,zlib
c=sqlite3.connect('file:/opt/shotcrypto/model_library/monitor-v1.sqlite3?mode=ro',uri=True)
row=c.execute("select at_ms,payload from events where kind='EVALUATION' order by at_ms desc limit 1").fetchone()
v=json.loads(zlib.decompress(row[1]));d=v['decision']
assert d['engineVersion']=='Crypto-G V1.16' and len(d['research'])==2
assert all(r['mode']=='SHADOW' for r in d['research'])
assert c.execute("select count(*) from outbox where id like 'recovery-shadow-%'").fetchone()[0]==0
print(json.dumps({'atMs':row[0],'persistedVersion':d['engineVersion'],'research':[{'variant':r['variant'],'status':r['status']} for r in d['research']],'researchOutboxCount':0}))
